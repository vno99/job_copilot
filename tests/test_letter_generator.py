"""Tests unitaires de la génération de lettre de motivation par LLM.

Couvre le nettoyage de la lettre (``privacy.anonymize.clean_letter_markdown`` —
la lettre générée reste **anonyme**, aucune coordonnée n'est réinjectée) et le
module de génération ``letter_generator_llm`` : construction du prompt (aucune
troncature du CV), appel du LLM, levée de ``LetterGenerationError`` (pas de
fallback pour la pass 1) et la **pass 2** (``humanize_letter_markdown``) :
réécriture humanisée systématique best-effort (fallback sur la pass 1 en cas
d'échec). Aucun LLM réel ni base de données requis.
"""

from types import SimpleNamespace

import pytest

from src.core.privacy.anonymize import clean_letter_markdown
from src.core.scoring import score_engine
from src.core.scoring.letter_generator_llm import (
    FIRST_LETTER_MARKER,
    LETTER_MARKER,
    REWRITE_MARKER,
    LetterGenerationError,
    _build_prompt,
    _build_rewrite_prompt,
    generate_letter_markdown,
    humanize_letter_markdown,
)
from src.core.scoring.llm_matcher import JOB_MARKER, PROFILE_MARKER


def _letter_profile_dict():
    return {
        "raw_cv": "# [NOM]\n\n## Compétences\n- Python\n- SQL\n- Airflow",
    }


def _letter_job_dict():
    return {
        "title": "Data Engineer",
        "company": "Alfi",
        "location": "Paris",
        "description": "Python SQL Databricks pour la construction de pipelines.",
    }


# ---------------------------------------------------------------------------
# clean_letter_markdown
# ---------------------------------------------------------------------------


def test_letter_clean_removes_placeholders():
    # Les placeholders résiduels du LLM sont retirés, jamais laissés visibles.
    out = clean_letter_markdown(
        "Madame, Monsieur,\n\nCordialement,\n[NOM]\n[EMAIL]", "Jean Dupont"
    )
    assert "[NOM]" not in out
    assert "[EMAIL]" not in out


def test_letter_clean_does_not_reinject_contact():
    # La lettre est anonyme : ni le nom réel ni les coordonnées capturées ne
    # sont réinjectés en fin de lettre.
    out = clean_letter_markdown(
        "Madame, Monsieur,\n\nCordialement,\n[NOM]\n[EMAIL]", "Jean Dupont"
    )
    assert "Jean" not in out
    assert "Jean Dupont" not in out
    assert "jean@ex.com" not in out


def test_letter_clean_removes_contact_line():
    # Ligne de coordonnées écrite par le LLM (placeholders ``|``) : retirée.
    md = "Cordialement,\n[EMAIL] | [TÉLÉPHONE] | [VILLE] | [LINKEDIN]"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert out == "Cordialement,"
    assert "[TÉLÉPHONE]" not in out
    assert "[LINKEDIN]" not in out


def test_letter_clean_removes_placeholder_without_value():
    # Un placeholder isolé (sans valeur à réinjecter) est retiré.
    out = clean_letter_markdown(
        "Cordialement,\n[TÉLÉPHONE]", "Jean Dupont"
    )
    assert "[TÉLÉPHONE]" not in out


def test_letter_clean_strips_leading_identity():
    # Un éventuel en-tête d'identité écrit par le LLM est retiré.
    md = "# [NOM]\n\nMadame, Monsieur,\n\nCordialement,\n[NOM]"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert not out.startswith("# [NOM]")
    assert not out.startswith("# Jean Dupont")
    assert "Madame, Monsieur" in out


def test_letter_clean_ignores_heading_with_real_name():
    # En-tête portant le nom réel (paramètre ``name``) : retiré lui aussi.
    md = "# Jean Dupont\n\nMadame, Monsieur,\n\nCordialement,"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert not out.startswith("# Jean Dupont")
    assert "Madame, Monsieur" in out


def test_letter_clean_keeps_real_section_title():
    # Une rubrique légitime (`# Résumé`) n'est jamais retirée.
    md = "# Résumé\n\nMadame, Monsieur,\n\nCordialement,"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert "# Résumé" in out


def test_letter_clean_empty_markdown():
    assert clean_letter_markdown("", "Jean Dupont") == ""


def test_letter_clean_preserves_paragraphs():
    # Les lignes vides (séparation des paragraphes) sont conservées : sans
    # elles, le Markdown afficherait la lettre en un seul paragraphe collé.
    md = "Madame, Monsieur,\n\nJe souhaite postuler au poste.\n\nCordialement,"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert "Madame, Monsieur,\n\nJe souhaite postuler" in out
    assert "postuler au poste.\n\nCordialement," in out


def test_letter_clean_removes_name_line():
    # L'anonymisation remplace chaque mot du nom par ``[NOM]`` ; le LLM peut
    # reproduire ``[NOM] [NOM]`` (voire en gras) en signature. Cette ligne de
    # nom est retirée — le nom réel n'est jamais réinjecté.
    md = "Cordialement,\n[NOM] [NOM]"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert out == "Cordialement,"
    assert "Jean Dupont" not in out

    md_bold = "Cordialement,\n**[NOM] [NOM]**"
    out_bold = clean_letter_markdown(md_bold, "Jean Dupont")
    assert out_bold == "Cordialement,"
    assert "Jean Dupont" not in out_bold


def test_letter_clean_removes_partial_contact_line():
    # Ligne de coordonnées partielle du LLM : retirée, aucun `` |  |  | ``
    # résiduel n'est laissé.
    md = "Cordialement,\n[NOM]\n[EMAIL] | [TÉLÉPHONE]"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert "[TÉLÉPHONE]" not in out
    assert "|  |" not in out
    assert "|" not in out


def test_letter_clean_keeps_no_signature():
    # La lettre se termine par la formule de politesse, sans nom ni coordonnées.
    md = "Madame, Monsieur,\n\nJe reste à votre disposition.\n\nCordialement,"
    out = clean_letter_markdown(md, "Jean Dupont")
    assert out.endswith("Cordialement,")
    assert "Jean" not in out
    assert "[NOM]" not in out


# ---------------------------------------------------------------------------
# generate_letter_markdown
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, content: str = "", error: Exception | None = None):
        self._content = content
        self._error = error

    def invoke(self, _messages):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=self._content)


def test_generate_letter_markdown_returns_llm_response(monkeypatch):
    monkeypatch.setattr(
        score_engine,
        "GENERATION_LLM",
        _FakeLLM(content="Madame, Monsieur,\n\nCordialement,\n[NOM]"),
    )
    md = generate_letter_markdown(_letter_job_dict(), _letter_profile_dict())
    assert "Cordialement" in md


def test_generate_letter_markdown_strips_code_fences(monkeypatch):
    monkeypatch.setattr(
        score_engine,
        "GENERATION_LLM",
        _FakeLLM(content="```markdown\nMadame, Monsieur,\n\nCordialement,\n```"),
    )
    md = generate_letter_markdown(_letter_job_dict(), _letter_profile_dict())
    assert md.startswith("Madame, Monsieur")
    assert "```" not in md


def test_generate_letter_markdown_raises_without_key(monkeypatch):
    monkeypatch.setattr(score_engine, "GENERATION_LLM", None)
    with pytest.raises(LetterGenerationError):
        generate_letter_markdown(_letter_job_dict(), _letter_profile_dict())


def test_generate_letter_markdown_raises_on_empty_response(monkeypatch):
    monkeypatch.setattr(
        score_engine, "GENERATION_LLM", _FakeLLM(content="   ")
    )
    with pytest.raises(LetterGenerationError):
        generate_letter_markdown(_letter_job_dict(), _letter_profile_dict())


def test_generate_letter_markdown_raises_on_api_error(monkeypatch):
    monkeypatch.setattr(
        score_engine, "GENERATION_LLM", _FakeLLM(error=RuntimeError("API down"))
    )
    with pytest.raises(LetterGenerationError):
        generate_letter_markdown(_letter_job_dict(), _letter_profile_dict())


# ---------------------------------------------------------------------------
# Construction du prompt
# ---------------------------------------------------------------------------


def test_letter_build_prompt_contains_markers_and_instructions():
    prompt = _build_prompt(_letter_job_dict(), _letter_profile_dict())
    assert JOB_MARKER in prompt
    assert PROFILE_MARKER in prompt
    assert LETTER_MARKER in prompt
    assert "RÈGLES STRICTES" in prompt


def test_letter_build_prompt_does_not_truncate_long_cv():
    # Contrairement au matching (MAX_CV_CHARS), la génération transmet le CV
    # intégralement : la lettre doit s'appuyer sur tous les faits du candidat.
    raw_cv = "# [NOM]\n\n## Compétences\n- " + "x" * 9000
    prompt = _build_prompt(_letter_job_dict(), {"raw_cv": raw_cv})
    assert ("x" * 9000) in prompt


# ---------------------------------------------------------------------------
# humanize_letter_markdown (pass 2 : réécriture « humaine » systématique)
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


_FIRST_LETTER = "Madame, Monsieur,\n\nFort de mes pipelines Airflow,\n\nCordialement,"


def _patch_two_pass(monkeypatch, pass1_responses, pass2_responses):
    """Patche ``GENERATION_LLM`` (pass 1) et ``HUMANIZE_LLM`` (pass 2).

    La pass 1 et la pass 2 utilisent deux instances distinctes : chacune reçoit
    sa propre file de réponses scriptées.

    Returns:
        (llm_pass1, llm_pass2) — pour inspecter les prompts reçus par chaque
        instance.
    """
    llm_pass1 = _ScriptedLLM(*pass1_responses)
    llm_pass2 = _ScriptedLLM(*pass2_responses)
    monkeypatch.setattr(score_engine, "GENERATION_LLM", llm_pass1)
    monkeypatch.setattr(score_engine, "HUMANIZE_LLM", llm_pass2)
    return llm_pass1, llm_pass2


def test_humanize_always_rewrites(monkeypatch):
    # Pas de juge : la pass 2 réécrit systématiquement la lettre de la pass 1.
    rewritten = "On m'a dit que je parlais de mes pipelines...\n\nCordialement,"
    llm_pass1, llm_pass2 = _patch_two_pass(
        monkeypatch,
        pass1_responses=[_FIRST_LETTER],
        pass2_responses=[rewritten],
    )
    out = humanize_letter_markdown(_letter_job_dict(), _letter_profile_dict())
    assert out == rewritten
    assert len(llm_pass1.prompts) == 1
    assert len(llm_pass2.prompts) == 1  # réécriture uniquement, pas de juge
    # Le prompt de réécriture embarque bien la 1re lettre.
    assert _FIRST_LETTER in llm_pass2.prompts[0]


def test_humanize_falls_back_when_rewrite_api_error(monkeypatch):
    # La réécriture échoue (erreur API) : fallback sur la pass 1, rien ne lève.
    _patch_two_pass(
        monkeypatch,
        pass1_responses=[_FIRST_LETTER],
        pass2_responses=[RuntimeError("API down")],
    )
    out = humanize_letter_markdown(_letter_job_dict(), _letter_profile_dict())
    assert out == _FIRST_LETTER


def test_humanize_falls_back_when_rewrite_empty(monkeypatch):
    # Réécriture vide : LetterGenerationError interne → fallback pass 1.
    _patch_two_pass(
        monkeypatch,
        pass1_responses=[_FIRST_LETTER],
        pass2_responses=["   "],
    )
    out = humanize_letter_markdown(_letter_job_dict(), _letter_profile_dict())
    assert out == _FIRST_LETTER


def test_humanize_raises_when_pass1_fails(monkeypatch):
    # La pass 1 exige le LLM : sans clé, LetterGenerationError (pas de fallback).
    monkeypatch.setattr(score_engine, "GENERATION_LLM", None)
    with pytest.raises(LetterGenerationError):
        humanize_letter_markdown(_letter_job_dict(), _letter_profile_dict())


def test_rewrite_build_prompt_contains_first_letter_and_markers():
    prompt = _build_rewrite_prompt(
        _letter_job_dict(), _letter_profile_dict(), _FIRST_LETTER
    )
    assert FIRST_LETTER_MARKER in prompt
    assert _FIRST_LETTER in prompt
    assert JOB_MARKER in prompt
    assert PROFILE_MARKER in prompt
    assert REWRITE_MARKER in prompt
    # Le marqueur de la pass 1 est absent : le mock du conftest ne doit pas
    # re-brancher sur la génération simple de la lettre.
    assert LETTER_MARKER not in prompt
