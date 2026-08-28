"""Tests de la classification/extraction d'offres depuis une URL
(``src/core/scoring/url_offer_extractor.py``).

Le LLM est mocké au niveau de ``score_engine.URL_SCRAPER_LLM`` (le fixture
autouse ``_mock_llm`` du conftest le remplace déjà ; ces tests le surchargent
par réponse explicite quand ils veulent un cas particulier).
"""

import json
from types import SimpleNamespace

import pytest

from src.core.scoring import score_engine
from src.core.scoring.url_offer_extractor import (
    LIST_MAX_URLS,
    MAX_PAGE_CHARS,
    LLMExtractionError,
    URL_OFFER_MARKER,
    URLScrapingError,
    PageResult,
    _build_prompt,
    extract_offer,
    extract_page,
)


def _valid_payload(**overrides):
    payload = {
        "title": "Data Engineer H/F",
        "company": "Acme",
        "location": "Paris - 75",
        "contract_type": "CDI",
        "description": "Python SQL Databricks",
        "published_date": "2026-05-22",
        "experience": "3 ans",
        "diploma": "Bac +5",
    }
    payload.update(overrides)
    return payload


def _mock_llm(monkeypatch, raw: str, capture=None) -> None:
    """Remplace ``URL_SCRAPER_LLM`` par une réponse déterministe.

    ``capture`` : liste optionnelle recevant les ``messages`` de chaque ``invoke``.
    """

    def invoke(_messages):
        if capture is not None:
            capture.append(_messages)
        return SimpleNamespace(content=raw)

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=invoke)
    )


def _mock_llm_with_metadata(monkeypatch, raw: str, metadata: dict) -> None:
    """Comme ``_mock_llm`` mais avec une ``response_metadata`` (finish_reason)."""

    def invoke(_messages):
        return SimpleNamespace(content=raw, response_metadata=metadata)

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=invoke)
    )


def _single_payload(**overrides):
    return {"page_type": "single", "offer": _valid_payload(**overrides)}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_marker_and_page_text():
    prompt = _build_prompt("Data Engineer chez Acme")
    assert URL_OFFER_MARKER in prompt
    assert "Data Engineer chez Acme" in prompt
    # Aucun marqueur réservé au mock (extraction de compétences, matching) :
    # sinon la branche du conftest ne serait pas distinguée du fallback skills.
    assert "OFFRE À ANALYSER :" not in prompt
    assert "=== PROFIL CANDIDAT ===" not in prompt


def test_build_prompt_main_content_philosophy():
    """Le prompt de classification pose le principe « contenu principal vs
    contenu secondaire » (règle 0) : seul le contenu principal détermine le type
    de page, le contenu secondaire (similaires, navigation, pied de page) ne
    contribue jamais à l'offre extraite."""
    prompt = _build_prompt("page")
    assert "CONTENU PRINCIPAL" in prompt
    assert "contenu secondaire" in prompt
    assert "ne détermine JAMAIS le type de page" in prompt
    assert "contribue JAMAIS à l'offre extraite" in prompt


def test_build_prompt_detail_never_list_even_with_links():
    """Une page de détail n'est jamais classée en liste, même si elle contient
    beaucoup de liens ou d'autres offres (ne pas classer « list » sur la seule
    présence de liens)."""
    prompt = _build_prompt("page")
    assert "Une page de détail n'est jamais une liste" in prompt
    assert "elle contient beaucoup de liens" in prompt


def test_build_prompt_list_classified_by_function_not_link_count():
    """Une liste est classée « list » par SA FONCTION (ensemble de résultats),
    pas par la quantité de liens — même une liste à une seule offre est une
    liste."""
    prompt = _build_prompt("page")
    assert "par SA FONCTION" in prompt
    assert "elle ne contient qu'une seule" in prompt


def test_build_prompt_secondary_content_never_into_description():
    """La règle 0 interdit que le contenu secondaire entre dans la description,
    en complément de la règle « description » qui exige de retranscrire TOUT
    l'offre sans copier les offres similaires."""
    prompt = _build_prompt("page")
    assert "ni à sa description, ni à ses URLs" in prompt
    assert "TOUT le texte de l'offre" in prompt
    assert "N'y copie JAMAIS de texte provenant des offres « similaires »" in prompt


def test_build_prompt_description_rule_keeps_full_offer():
    """La règle « description » du prompt exige de retranscrire TOUT le texte de
    l'offre (salaire, avantages, référence) et d'ignorer les offres similaires."""
    prompt = _build_prompt("page")
    assert "TOUT le texte de l'offre" in prompt
    assert "salaire/rémunération" in prompt
    assert "N'y copie JAMAIS de texte provenant des offres « similaires »" in prompt


def test_build_prompt_truncates_long_page_text():
    long_text = "x" * (MAX_PAGE_CHARS * 2)
    prompt = _build_prompt(long_text)
    assert URL_OFFER_MARKER in prompt
    # Le texte est borné à ``MAX_PAGE_CHARS`` + le caractère de coupure "…".
    assert "x" * MAX_PAGE_CHARS + "…" in prompt
    assert "x" * (MAX_PAGE_CHARS + 1) not in prompt


def test_build_prompt_includes_max_urls():
    prompt = _build_prompt("page", max_urls=7)
    assert URL_OFFER_MARKER in prompt
    # Le plafond est transmis au LLM (« au plus 7 URLs » pour une liste).
    assert "7" in prompt


def test_build_prompt_single_only_omits_list_option():
    """Prompt mono-offre (``single_only``) : « list » n'est plus une option — une
    page de détail avec offres similaires ne doit pas être classée en liste."""
    prompt = _build_prompt("page", single_only=True)
    assert URL_OFFER_MARKER in prompt
    # Consigne explicite anti-« list ».
    assert "JAMAIS" in prompt
    # Aucune règle ni exemple de réponse « list » (le mot « list » ne figure que
    # dans la consigne « Ne renvoie JAMAIS ... », à titre d'interdiction).
    assert "Si la page contient une LISTE" not in prompt
    assert '"offers": [' not in prompt
    assert '"url": "https://example.com/offres/data-analyst"' not in prompt
    # L'exemple d'offre unique (avec champs) reste présent.
    assert '"url": "https://example.com/offres/data-engineer"' in prompt


def test_build_prompt_single_only_main_content_philosophy():
    """Le prompt mono-offre pose le principe contenu principal/secondaire : une
    page de détail a pour contenu principal UNE offre, les offres similaires
    sont secondaires et ne déterminent jamais le type de page."""
    prompt = _build_prompt("page", single_only=True)
    assert "CONTENU PRINCIPAL" in prompt
    assert "UNE offre d'emploi" in prompt
    assert "elle contient beaucoup de" in prompt
    assert "Ne renvoie JAMAIS" in prompt


def test_build_prompt_classification_still_offers_list():
    """Prompt de classification (défaut) : l'option « list » reste proposée."""
    prompt = _build_prompt("page")
    assert '"page_type": "list"' in prompt
    assert '"offers": [' in prompt  # exemple de réponse « list »


# ---------------------------------------------------------------------------
# Classification « single » (la page EST une offre)
# ---------------------------------------------------------------------------


def test_extract_page_single_parses_valid_response(monkeypatch):
    messages_seen = []
    _mock_llm(
        monkeypatch,
        json.dumps(_single_payload(), ensure_ascii=False),
        capture=messages_seen,
    )
    result = extract_page("texte de la page")

    assert isinstance(result, PageResult)
    assert result.page_type == "single"
    assert result.offer == {
        "title": "Data Engineer H/F",
        "company": "Acme",
        "location": "Paris - 75",
        "contract_type": "CDI",
        "description": "Python SQL Databricks",
        "published_date": "2026-05-22",
        "experience": "3 ans",
        "diploma": "Bac +5",
        "url": None,  # pas d'URL individuelle dans une page d'offre unique
        "reason": None,  # champ "reason" absent d'une réponse d'offre valide
    }
    assert result.urls == []

    # L'instance est invoquée avec [SystemMessage, HumanMessage], le prompt
    # embarque le marqueur dédié.
    assert len(messages_seen) == 1
    system, human = messages_seen[0]
    assert type(system).__name__ == "SystemMessage"
    assert type(human).__name__ == "HumanMessage"
    assert URL_OFFER_MARKER in human.content


def test_extract_page_accepts_bare_offer_dict(monkeypatch):
    """Parsing tolérant : un dict d'offre sans ``page_type`` → ``single``
    (rétro-compat : mock du conftest, le LLM pouvant renvoyer l'un ou l'autre)."""
    _mock_llm(monkeypatch, json.dumps(_valid_payload(), ensure_ascii=False))
    result = extract_page("page")
    assert result.page_type == "single"
    assert result.offer["title"] == "Data Engineer H/F"


def test_extract_page_single_normalizes_missing_fields(monkeypatch):
    """Champs absents → None (hors title/description, vides → chaîne vide)."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            _single_payload(
                title="  Data Engineer  ",
                description="  Python  ",
                company=None,
                location=None,
                contract_type=None,
                published_date=None,
                experience=None,
                diploma=None,
            ),
            ensure_ascii=False,
        ),
    )
    result = extract_page("page")
    assert result.page_type == "single"
    offer = result.offer
    assert offer["title"] == "Data Engineer"
    assert offer["description"] == "Python"
    assert offer["company"] is None
    assert offer["location"] is None
    assert offer["contract_type"] is None
    assert offer["published_date"] is None
    assert offer["experience"] is None
    assert offer["diploma"] is None
    assert offer["url"] is None
    assert offer["reason"] is None


# ---------------------------------------------------------------------------
# Classification « liste » (les URLs des offres, pas leur contenu)
# ---------------------------------------------------------------------------


def test_extract_page_list_returns_urls_in_order(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [
                    {"url": "https://example.com/offres/data-engineer"},
                    {"url": "https://example.com/offres/data-analyst"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    result = extract_page("page")
    assert result.page_type == "list"
    assert result.urls == [
        "https://example.com/offres/data-engineer",
        "https://example.com/offres/data-analyst",
    ]
    assert result.offer is None


def test_extract_page_list_normalizes_urls(monkeypatch):
    """Fragment retiré, non-http ignoré, éléments non-dicts ignorés."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [
                    {"url": "https://example.com/o1#top"},
                    {"url": "javascript:alert(1)"},
                    {"url": "https://example.com/o2"},
                    "pas un dict",
                ],
            },
            ensure_ascii=False,
        ),
    )
    result = extract_page("page")
    assert result.urls == ["https://example.com/o1", "https://example.com/o2"]


def test_extract_page_list_caps_at_max_urls(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [{"url": f"https://example.com/o{i}"} for i in range(5)],
            },
            ensure_ascii=False,
        ),
    )
    result = extract_page("page", max_urls=2)
    assert result.page_type == "list"
    assert len(result.urls) == 2


def test_extract_page_list_caps_at_default_limit(monkeypatch):
    """Défense serveur : la borne par défaut ``LIST_MAX_URLS`` est appliquée."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [
                    {"url": f"https://example.com/o{i}"} for i in range(LIST_MAX_URLS + 5)
                ],
            },
            ensure_ascii=False,
        ),
    )
    result = extract_page("page")
    assert len(result.urls) == LIST_MAX_URLS


def test_extract_page_list_accepts_french_offres_key(monkeypatch):
    """Tolérance clé française : le LLM renvoie parfois « offres » au lieu de
    « offers » (cause racine du 422 intermittent sur la page de recherche) —
    les deux clés sont acceptées."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offres": [{"url": "https://example.com/o1"}],
            },
            ensure_ascii=False,
        ),
    )
    result = extract_page("page")
    assert result.page_type == "list"
    assert result.urls == ["https://example.com/o1"]


def test_extract_page_list_empty_message_includes_reason(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            {"page_type": "list", "offers": [], "reason": "la page est une page d'accueil"}
        ),
    )
    with pytest.raises(URLScrapingError, match="page d'accueil"):
        extract_page("page")


def test_extract_page_list_all_invalid_urls_raises(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [{"url": "javascript:x"}, {"url": "ftp://x"}],
            }
        ),
    )
    with pytest.raises(URLScrapingError):
        extract_page("page")


def test_extract_page_single_only_rejects_list_response(monkeypatch):
    """Mode mono-offre : une réponse « list » est refusée — c'est le cas d'une
    page de détail (offre principale + offres similaires) classée à tort en
    liste par le LLM → URLScrapingError."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "list",
                "offers": [{"url": "https://example.com/o1"}],
            }
        ),
    )
    with pytest.raises(URLScrapingError):
        extract_page("page", single_only=True)


# ---------------------------------------------------------------------------
# Page « none » (rien d'exploitable)
# ---------------------------------------------------------------------------


def test_extract_page_none_message_includes_reason(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "none",
                "reason": "l'offre n'est plus disponible sur le site",
            }
        ),
    )
    with pytest.raises(URLScrapingError, match="n'est plus disponible sur le site"):
        extract_page("page")


# ---------------------------------------------------------------------------
# Erreurs communes
# ---------------------------------------------------------------------------


def test_extract_page_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", None)
    with pytest.raises(LLMExtractionError):
        extract_page("page")


def test_extract_page_raises_on_malformed_json(monkeypatch):
    _mock_llm(monkeypatch, "pas du json")
    with pytest.raises(LLMExtractionError):
        extract_page("page")


def test_extract_page_raises_truncated_response_flag(monkeypatch):
    """Une réponse coupée par le budget de tokens (``finish_reason=length``) est
    signalée comme tronquée dans le message — diagnostic de troncature (le
    « LLM indisponible » de l'agent est alors trompeur)."""
    _mock_llm_with_metadata(
        monkeypatch,
        # Chaîne coupée en plein milieu (aucune fermeture du JSON).
        '{"page_type": "single", "offer": {"title": "Data Engineer", '
        '"description": "Conception de pipelines',
        {"finish_reason": "length"},
    )
    with pytest.raises(LLMExtractionError, match="réponse LLM tronquée"):
        extract_page("page")


def test_extract_page_raises_malformed_json_not_truncated(monkeypatch):
    """Un saut de ligne littéral **dans une valeur** rend le JSON invalide sans
    troncature (``finish_reason=stop``) : le message reste générique."""
    _mock_llm_with_metadata(
        monkeypatch,
        '{"page_type": "single", "offer": {"title": "Data Engineer", '
        '"description": "Conception\nde pipelines"}}',
        {"finish_reason": "stop"},
    )
    with pytest.raises(LLMExtractionError) as excinfo:
        extract_page("page")
    assert "tronquée" not in str(excinfo.value)


def test_extract_page_raises_on_non_object_json(monkeypatch):
    _mock_llm(monkeypatch, "[]")
    with pytest.raises(LLMExtractionError):
        extract_page("page")


def test_extract_page_raises_on_api_error(monkeypatch):
    def _boom(_messages):
        raise ConnectionError("réseau coupé")

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=_boom)
    )
    with pytest.raises(LLMExtractionError):
        extract_page("page")


# ---------------------------------------------------------------------------
# Wrapper mono-offre (extract_offer)
# ---------------------------------------------------------------------------


def test_extract_offer_parses_valid_response(monkeypatch):
    _mock_llm(monkeypatch, json.dumps(_single_payload(), ensure_ascii=False))
    result = extract_offer("texte de la page")
    assert result["title"] == "Data Engineer H/F"
    assert result["company"] == "Acme"
    assert result["url"] is None


def test_extract_offer_accepts_bare_offer_dict(monkeypatch):
    """Parsing tolérant du wrapper : dict d'offre sans ``page_type`` → single."""
    _mock_llm(monkeypatch, json.dumps(_valid_payload(), ensure_ascii=False))
    result = extract_offer("page")
    assert result["title"] == "Data Engineer H/F"


def test_extract_offer_strips_code_fences(monkeypatch):
    raw = "```json\n" + json.dumps(_single_payload(), ensure_ascii=False) + "\n```"
    _mock_llm(monkeypatch, raw)
    result = extract_offer("page")
    assert result["title"] == "Data Engineer H/F"
    assert result["company"] == "Acme"


def test_extract_offer_normalizes_missing_fields(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            _single_payload(
                title="  Data Engineer  ",
                description="  Python  ",
                company=None,
                location=None,
                contract_type=None,
                published_date=None,
                experience=None,
                diploma=None,
            )
        ),
    )
    result = extract_offer("page")
    assert result["title"] == "Data Engineer"
    assert result["description"] == "Python"
    assert result["company"] is None


def test_extract_offer_raises_on_list_page(monkeypatch):
    """Une réponse « list » est refusée par le wrapper mono-offre
    (``single_only``) → URLScrapingError."""
    _mock_llm(
        monkeypatch,
        json.dumps({"page_type": "list", "offers": [{"url": "https://example.com/o1"}]}),
    )
    with pytest.raises(URLScrapingError):
        extract_offer("page")


def test_extract_offer_raises_on_non_offer_page(monkeypatch):
    """Une page sans titre ni description n'est pas une offre → URLScrapingError."""
    _mock_llm(monkeypatch, '{"page_type": "single", "offer": {"title": "", "description": ""}}')
    with pytest.raises(URLScrapingError):
        extract_offer("page")


def test_extract_offer_non_offer_message_includes_reason(monkeypatch):
    """Le message d'``URLScrapingError`` reprend la ``reason`` du LLM."""
    _mock_llm(
        monkeypatch,
        json.dumps(
            {
                "page_type": "none",
                "reason": "l'offre n'est plus disponible sur le site",
            }
        ),
    )
    with pytest.raises(URLScrapingError, match="n'est plus disponible sur le site"):
        extract_offer("page")


def test_extract_offer_raises_when_title_missing(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(_single_payload(title="", description="Python")),
    )
    with pytest.raises(URLScrapingError):
        extract_offer("page")


def test_extract_offer_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", None)
    with pytest.raises(LLMExtractionError):
        extract_offer("page")


def test_extract_offer_raises_on_malformed_json(monkeypatch):
    _mock_llm(monkeypatch, "pas du json")
    with pytest.raises(LLMExtractionError):
        extract_offer("page")


def test_extract_offer_raises_on_api_error(monkeypatch):
    def _boom(_messages):
        raise ConnectionError("réseau coupé")

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=_boom)
    )
    with pytest.raises(LLMExtractionError):
        extract_offer("page")
