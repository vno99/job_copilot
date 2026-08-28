"""Tests unitaires de la génération de CV par LLM.

Couvre l'extraction et la réinjection des coordonnées (``privacy.anonymize``)
et le module de génération ``cv_generator_llm`` : construction du prompt (aucune
troncature du CV), appel du LLM, levée de ``CVGenerationError`` (pas de fallback
pour la pass 1) et ``humanize_cv_markdown`` — **une passe** : la pass 2
(réécriture « humaine ») est désactivée, la fonction retourne directement le CV
de la pass 1.
Aucun LLM réel ni base de données requis.
"""

from types import SimpleNamespace

import pytest

from src.core.privacy.anonymize import extract_contact_info, inject_contact_info
from src.core.scoring import score_engine
from src.core.scoring.cv_generator_llm import (
    COMPATIBILITY_MARKER,
    CV_REWRITE_MARKER,
    FIRST_CV_MARKER,
    JOB_MARKER,
    PROFILE_MARKER,
    CVGenerationError,
    _build_prompt,
    _build_rewrite_prompt,
    _split_collapsed_table_rows,
    generate_cv_markdown,
    humanize_cv_markdown,
)


def _profile_dict():
    return {
        "raw_cv": "# [NOM]\n\n## Compétences\n- Python\n- SQL\n- Airflow",
    }


def _job_dict():
    return {
        "title": "Data Engineer",
        "company": "Alfi",
        "location": "Paris",
        "description": "Python SQL Databricks pour la construction de pipelines.",
    }


def _match_dict():
    return {
        "score": 72.0,
        "score_breakdown": {},
        "strengths": [],
        "weaknesses": [],
        "missing_skills": ["Kubernetes"],
        "explanation": "",
    }


def _empty_contact():
    return {"name": "", "email": "", "phone": "", "linkedin": "", "location": ""}


# ---------------------------------------------------------------------------
# extract_contact_info
# ---------------------------------------------------------------------------


def test_extract_contact_info_full():
    text = (
        "# Jean Dupont\n\n"
        "77360 VAIRES SUR MARNE | jean.dupont@example.com | 06 59 19 35 72 | "
        "linkedin.com/in/jean-dupont"
    )
    info = extract_contact_info(text)
    assert info["name"] == "Jean Dupont"
    assert info["email"] == "jean.dupont@example.com"
    assert info["phone"] == "06 59 19 35 72"
    assert info["location"] == "77360 VAIRES SUR MARNE"
    assert info["linkedin"] == "linkedin.com/in/jean-dupont"


def test_extract_contact_info_bold_name():
    text = "**NOUANE Victor**\n\nPython / SQL\nnouane_v@hotmail.com"
    info = extract_contact_info(text)
    assert info["name"] == "NOUANE Victor"
    assert info["email"] == "nouane_v@hotmail.com"


def test_extract_contact_info_empty():
    text = "# Jean Dupont\n\n## Compétences\n- Python"
    info = extract_contact_info(text)
    assert info["name"] == "Jean Dupont"
    assert info["email"] == ""
    assert info["phone"] == ""
    assert info["linkedin"] == ""
    assert info["location"] == ""


def test_extract_contact_info_section_title_not_name():
    # La première rubrique (`## Résumé`) ne doit jamais être prise pour un nom.
    text = "## Résumé\nData Engineer.\n## Compétences\n- Python"
    info = extract_contact_info(text)
    assert info["name"] == ""


# ---------------------------------------------------------------------------
# inject_contact_info
# ---------------------------------------------------------------------------


def test_inject_builds_header_and_keeps_body():
    contact = dict(_empty_contact(), name="Jean Dupont", email="jean@ex.com")
    out = inject_contact_info("## Compétences\n- Python", contact)
    assert out.startswith("# Jean Dupont\njean@ex.com")
    assert "## Compétences\n- Python" in out


def test_inject_replaces_placeholders_in_body():
    contact = dict(_empty_contact(), email="jean@ex.com")
    out = inject_contact_info("## Compétences\n- Python\nContact : [EMAIL]", contact)
    assert "[EMAIL]" not in out
    assert "Contact : jean@ex.com" in out


def test_inject_removes_llm_identity_header():
    # `# [NOM]` écrit par le LLM est retiré, l'en-tête réel est préfixé.
    contact = dict(_empty_contact(), name="Jean Dupont", email="jean@ex.com")
    md = "# [NOM]\n\n## Compétences\n- Python\n[EMAIL]"
    out = inject_contact_info(md, contact)
    assert out.startswith("# Jean Dupont")
    assert "[NOM]" not in out
    assert "[EMAIL]" not in out


def test_inject_removes_llm_contact_line():
    # Le LLM reproduit la ligne de coordonnées du CV anonymisé : elle doit être
    # retirée (l'en-tête serveur la réinjecte), pas dupliquée. Le pied de page
    # (contact non placé sous l'en-tête) est conservé.
    contact = dict(
        _empty_contact(),
        name="Jean Dupont",
        email="jean@ex.com",
        phone="06 59 19 35 72",
        location="75001 Paris",
        linkedin="linkedin.com/in/jean",
    )
    md = (
        "# [NOM]\n\n"
        "[EMAIL] | [TÉLÉPHONE] | [VILLE] | [LINKEDIN]\n"
        "Data Engineer | Software Engineering & Data Pipelines\n"
        "## Compétences\n- Python"
    )
    out = inject_contact_info(md, contact)
    # Le contact se place après le titre de poste, pas après le nom, dans
    # l'ordre ville | téléphone | email | linkedin (comme le CV original).
    assert out.startswith(
        "# Jean Dupont\n\n"
        "Data Engineer | Software Engineering & Data Pipelines  \n"
        "75001 Paris | 06 59 19 35 72 | jean@ex.com | linkedin.com/in/jean"
    )
    # La ligne de coordonnées du LLM a disparu : le contact n'apparaît qu'une fois.
    assert out.count("jean@ex.com") == 1
    assert out.index("jean@ex.com") > out.index("Data Engineer")


def test_inject_removes_contact_line_before_name():
    # La ligne de coordonnées peut précéder la ligne de nom : les deux sont
    # retirées, l'en-tête serveur reste unique.
    contact = dict(_empty_contact(), name="Jean Dupont", email="jean@ex.com")
    md = "[EMAIL] | [TÉLÉPHONE]\n# [NOM]\n\n## Compétences\n- Python"
    out = inject_contact_info(md, contact)
    assert out == "# Jean Dupont\njean@ex.com\n\n## Compétences\n- Python"


def test_inject_removes_repeated_name_placeholder():
    # Anonymisation d'un nom à plusieurs mots → `# [NOM] [NOM]` : retiré aussi.
    contact = dict(_empty_contact(), name="Jean Dupont", email="jean@ex.com")
    out = inject_contact_info("# [NOM] [NOM]\n\n## Compétences\n- Python", contact)
    assert out.startswith("# Jean Dupont")
    assert "Jean Dupont Jean Dupont" not in out


def test_inject_keeps_real_section_title():
    # `# Résumé` est une rubrique légitime : jamais retirée.
    contact = dict(_empty_contact(), name="Jean Dupont")
    out = inject_contact_info("# Résumé\n\nExpérimenté.", contact)
    assert out.startswith("# Jean Dupont")
    assert "# Résumé" in out


def test_inject_removes_placeholder_without_value():
    # Un placeholder dont la valeur n'a pas été capturée est retiré, jamais laissé.
    out = inject_contact_info("## Compétences\n- Python\nTél : [TÉLÉPHONE]", _empty_contact())
    assert "[TÉLÉPHONE]" not in out


def test_inject_removes_contact_line_anywhere():
    # La ligne de coordonnées reproduite par le LLM n'est pas toujours en tête :
    # elle doit être retirée où qu'elle soit, sinon l'en-tête serveur et la
    # ligne reproduite afficheraient le contact deux fois.
    contact = dict(
        _empty_contact(),
        name="Jean Dupont",
        email="jean@ex.com",
        phone="06 59 19 35 72",
    )
    md = (
        "# [NOM]\n\n"
        "## Résumé\n"
        "Data Engineer expérimenté.\n\n"
        "[EMAIL] | [TÉLÉPHONE]\n\n"
        "## Compétences\n- Python"
    )
    out = inject_contact_info(md, contact)
    # Pas de ville : téléphone avant email (même ordre, champs absents omis).
    assert out.startswith("# Jean Dupont\n06 59 19 35 72 | jean@ex.com")
    assert out.count("jean@ex.com") == 1
    assert "[EMAIL]" not in out and "[TÉLÉPHONE]" not in out
    assert "## Résumé" in out
    assert "## Compétences" in out


def test_inject_removes_contact_line_with_markdown_link():
    # Le LLM peut reproduire la ligne de coordonnées en conservant le lien
    # LinkedIn au format Markdown du CV anonymisé (``[LINKEDIN]([LINKEDIN])``) :
    # après retrait des placeholders il ne reste que des parenthèses — la ligne
    # doit quand même être reconnue comme une ligne de contact et retirée.
    contact = dict(
        _empty_contact(),
        name="NOUANE Victor",
        email="nouane_v@hotmail.com",
        phone="06 86 92 71 94",
        location="77360 VAIRES SUR MARNE",
        linkedin="linkedin.com/in/victor-nouane/",
    )
    md = (
        "# [NOM]\n\n"
        "**Data Engineer - Agentic AI & GenAI**  \\\n"
        "[VILLE] | [TÉLÉPHONE] | [EMAIL] | [LINKEDIN]([LINKEDIN])\n\n"
        "## Résumé\n"
        "Data Engineer expérimenté."
    )
    out = inject_contact_info(md, contact)
    # Le contact se place après le titre de poste (retour à la ligne dur déjà
    # présent), pas après le nom, dans l'ordre ville | téléphone | email | linkedin
    # (comme le CV original) ; la ligne de coordonnées du LLM (lien Markdown
    # inclus) a disparu.
    assert out.startswith(
        "# NOUANE Victor\n\n"
        "**Data Engineer - Agentic AI & GenAI**  \\\n"
        "77360 VAIRES SUR MARNE | 06 86 92 71 94 | nouane_v@hotmail.com"
    )
    assert out.count("nouane_v@hotmail.com") == 1
    assert out.count("06 86 92 71 94") == 1
    assert out.index("nouane_v@hotmail.com") > out.index("**Data Engineer")
    assert "[LINKEDIN]" not in out
    assert "**Data Engineer - Agentic AI & GenAI**" in out
    assert "## Résumé" in out
    assert "Data Engineer expérimenté." in out


def test_inject_removes_contact_line_prefixed_by_name():
    # Le LLM peut écrire le nom et les coordonnées sur une seule ligne :
    # ``[NOM] | [EMAIL] | [TÉLÉPHONE]`` est une ligne de contact, retirée.
    contact = dict(_empty_contact(), name="Jean Dupont", email="jean@ex.com")
    md = "[NOM] | [EMAIL] | [TÉLÉPHONE]\n\n## Compétences\n- Python"
    out = inject_contact_info(md, contact)
    assert out.startswith("# Jean Dupont\njean@ex.com")
    assert out.count("jean@ex.com") == 1
    assert "[NOM]" not in out


def test_inject_empty_markdown():
    assert inject_contact_info("", _empty_contact()) == ""


# ---------------------------------------------------------------------------
# generate_cv_markdown
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, content: str = "", error: Exception | None = None):
        self._content = content
        self._error = error

    def invoke(self, _messages):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=self._content)


def test_generate_cv_markdown_returns_llm_response(monkeypatch):
    monkeypatch.setattr(
        score_engine, "CV_GENERATION_LLM", _FakeLLM(content="## Compétences\n- Python")
    )
    md = generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())
    assert "## Compétences" in md


def test_generate_cv_markdown_strips_code_fences(monkeypatch):
    monkeypatch.setattr(
        score_engine,
        "CV_GENERATION_LLM",
        _FakeLLM(content="```markdown\n## Compétences\n- Python\n```"),
    )
    md = generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())
    assert md.startswith("## Compétences")
    assert "```" not in md


def test_generate_cv_markdown_raises_without_key(monkeypatch):
    monkeypatch.setattr(score_engine, "CV_GENERATION_LLM", None)
    with pytest.raises(CVGenerationError):
        generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())


def test_generate_cv_markdown_raises_on_empty_response(monkeypatch):
    monkeypatch.setattr(score_engine, "CV_GENERATION_LLM", _FakeLLM(content="   "))
    with pytest.raises(CVGenerationError):
        generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())


def test_generate_cv_markdown_raises_on_api_error(monkeypatch):
    monkeypatch.setattr(
        score_engine, "CV_GENERATION_LLM", _FakeLLM(error=RuntimeError("API down"))
    )
    with pytest.raises(CVGenerationError):
        generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())


# ---------------------------------------------------------------------------
# Construction du prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_markers_and_instructions():
    prompt = _build_prompt(_job_dict(), _profile_dict(), _match_dict())
    assert JOB_MARKER in prompt
    assert PROFILE_MARKER in prompt
    assert COMPATIBILITY_MARKER in prompt
    assert '"score": 72.0' in prompt
    # Le prompt a été réécrit dans le cadre « recomposition ciblée » : le CV
    # source reste la seule source de vérité, l'offre ne sert qu'à hiérarchiser
    # les informations existantes (les règles de fond vivent dans SYSTEM_PROMPT).
    assert "Recompose le CV source" in prompt
    assert "la seule source de vérité" in prompt
    assert "recomposition de la présentation" in prompt
    assert "le CV recomposé" in prompt


def test_build_prompt_does_not_truncate_long_cv():
    # Contrairement au matching (MAX_CV_CHARS), la génération transmet le CV
    # intégralement : la mise en forme doit arriver intacte au LLM.
    raw_cv = "# [NOM]\n\n## Compétences\n- " + "x" * 9000
    prompt = _build_prompt(_job_dict(), {"raw_cv": raw_cv}, _match_dict())
    assert ("x" * 9000) in prompt


# ---------------------------------------------------------------------------
# humanize_cv_markdown (une passe — pass 2 désactivée)
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Serve les réponses en file ; mémorise les prompts utilisateur reçus.

    Un élément de la file peut être une exception (levée à l'invocation) pour
    simuler une erreur API. Un appel au-delà de la file lève ``RuntimeError``,
    pour détecter une réécriture inattendue (ou son absence).
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.prompts = []

    def invoke(self, _messages):
        self.prompts.append(_messages[-1].content)
        if not self._responses:
            raise RuntimeError("_ScriptedLLM : plus aucune réponse en file")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


# Sans saut de ligne final : la pass 1 passe par ``_strip_code_fences``
# (``.strip()``), le CV renvoyé n'a donc jamais de blanc final.
_FIRST_CV = (
    "# [NOM]\n\n"
    "## Résumé\n"
    "Data Engineer expérimenté.\n\n"
    "## Compétences clés\n"
    "- Python\n"
    "- SQL\n"
    "- Airflow"
)


def _patch_two_pass(monkeypatch, pass1_responses, pass2_responses):
    """Patche ``CV_GENERATION_LLM`` (pass 1) et ``HUMANIZE_LLM`` (pass 2).

    La pass 1 et la pass 2 utilisent deux instances distinctes : chacune reçoit
    sa propre file de réponses scriptées.

    Returns:
        (llm_pass1, llm_pass2) — pour inspecter les prompts reçus par chaque
        instance.
    """
    llm_pass1 = _ScriptedLLM(*pass1_responses)
    llm_pass2 = _ScriptedLLM(*pass2_responses)
    monkeypatch.setattr(score_engine, "CV_GENERATION_LLM", llm_pass1)
    monkeypatch.setattr(score_engine, "HUMANIZE_LLM", llm_pass2)
    return llm_pass1, llm_pass2


def test_cv_humanize_returns_first_pass_without_rewrite(monkeypatch):
    # La pass 2 (réécriture « humaine ») est désactivée : humanize retourne
    # directement le CV de la pass 1, sans jamais appeler la réécriture.
    rewritten = (
        "# [NOM]\n\n## Résumé\nLe pipeline plantait toutes les nuits.\n"
        "## Compétences\n| Domaine | Technologies |"
    )
    llm_pass1, llm_pass2 = _patch_two_pass(
        monkeypatch,
        pass1_responses=[_FIRST_CV],
        pass2_responses=[rewritten],
    )
    out = humanize_cv_markdown(_job_dict(), _profile_dict(), _match_dict())
    assert out == _FIRST_CV
    assert len(llm_pass1.prompts) == 1
    # La pass 2 n'est jamais sollicitée : aucune réécriture, aucun fallback.
    assert llm_pass2.prompts == []


def test_cv_humanize_raises_when_pass1_fails(monkeypatch):
    # La pass 1 exige le LLM : sans clé, CVGenerationError (pas de fallback).
    monkeypatch.setattr(score_engine, "CV_GENERATION_LLM", None)
    with pytest.raises(CVGenerationError):
        humanize_cv_markdown(_job_dict(), _profile_dict(), _match_dict())


def test_cv_rewrite_build_prompt_contains_first_cv_and_markers():
    prompt = _build_rewrite_prompt(
        _job_dict(), _profile_dict(), _match_dict(), _FIRST_CV
    )
    assert FIRST_CV_MARKER in prompt
    assert _FIRST_CV in prompt
    assert JOB_MARKER in prompt
    assert PROFILE_MARKER in prompt
    assert COMPATIBILITY_MARKER in prompt
    assert CV_REWRITE_MARKER in prompt
    # Les marqueurs de la lettre sont absents : le mock du conftest ne doit pas
    # servir une lettre (ni re-brancher sur sa réécriture).
    assert "=== LETTRE DE MOTIVATION ===" not in prompt
    assert "=== RÉÉCRITURE HUMAINE ===" not in prompt


# ---------------------------------------------------------------------------
# _split_collapsed_table_rows (réparation des tableaux GFM collés)
# ---------------------------------------------------------------------------


def test_split_collapsed_table_rows():
    # Tableau tel que le LLM le produit parfois : rangées collées sur une seule
    # ligne (en-tête + séparateur + données). La réparation insère un saut de
    # ligne à chaque ``| |`` (fin de rangée + début de la suivante) ; la rangée
    # de séparation (``|----|----|``) reste intacte.
    collapsed = (
        "## Compétences\n"
        "| Domaine | Technologies & Outils | |---------------------------|--------|\n"
        "| Data Engineering | Python, SQL | | Cloud & DevOps | AWS S3 |"
    )
    fixed = _split_collapsed_table_rows(collapsed)
    assert fixed == (
        "## Compétences\n"
        "| Domaine | Technologies & Outils |\n"
        "|---------------------------|--------|\n"
        "| Data Engineering | Python, SQL |\n"
        "| Cloud & DevOps | AWS S3 |"
    )


def test_split_collapsed_table_rows_ignores_paragraphs_and_wellformed_tables():
    # Une ligne qui ne commence pas par ``|`` n'est jamais touchée.
    assert (
        _split_collapsed_table_rows("Un paragraphe | normal")
        == "Un paragraphe | normal"
    )
    # Un tableau déjà bien formé (une rangée par ligne) est renvoyé inchangé.
    well_formed = "| A | B |\n|---|---|\n| X | Y |"
    assert _split_collapsed_table_rows(well_formed) == well_formed


def test_generate_cv_markdown_splits_collapsed_table_rows(monkeypatch):
    # La réponse du LLM contient un tableau collé : la pass 1 le répare avant
    # de renvoyer le Markdown (remark-gfm pourra le rendre en <table>).
    monkeypatch.setattr(
        score_engine,
        "CV_GENERATION_LLM",
        _FakeLLM(
            content=(
                "## Compétences\n"
                "| Domaine | Outils | |---|---|\n"
                "| Python | SQL | | Cloud | AWS |"
            )
        ),
    )
    md = generate_cv_markdown(_job_dict(), _profile_dict(), _match_dict())
    assert "| Domaine | Outils |\n|---|---|\n| Python | SQL |\n| Cloud | AWS |" in md
