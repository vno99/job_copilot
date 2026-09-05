"""Tests du parsing tolérant de ``url_offer_extractor``.

Couvre :
- La clé française ``offres`` au lieu de ``offers``
- Les réponses avec page_type manquant (traitement en single)
- Les réponses avec JSON incomplet (clé manquante)
- Comportement de extract_offer (mono-offre)
"""

import json
from types import SimpleNamespace

import pytest

from src.core.scoring import score_engine
from src.core.scoring.url_offer_extractor import (
    LLMExtractionError,
    PageResult,
    URLScrapingError,
    extract_offer,
    extract_page,
)


def _mock_llm(monkeypatch, raw: str, finish_reason: str = "stop") -> None:
    """Remplace ``URL_SCRAPER_LLM`` par une réponse déterministe."""

    def invoke(_messages):
        return SimpleNamespace(
            content=raw,
            response_metadata={"finish_reason": finish_reason},
        )

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=invoke)
    )


class TestFrenchKeyParsing:
    """Le LLM peut écrire ``offres`` au lieu de ``offers``."""

    def test_page_result_accepts_offres_key(self, monkeypatch):
        """Une réponse avec ``offres`` (clé française) est parsée correctement."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "list",
                "offres": [
                    {"url": "https://example.com/job/1"},
                    {"url": "https://example.com/job/2"},
                ],
            }),
        )
        page = extract_page("some text")
        assert page.page_type == "list"
        assert page.urls == [
            "https://example.com/job/1",
            "https://example.com/job/2",
        ]

    def test_offres_key_with_empty_list(self, monkeypatch):
        """Une liste vide lève URLScrapingError."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "list",
                "offres": [],
            }),
        )
        with pytest.raises(URLScrapingError):
            extract_page("some text")

    def test_single_offer_with_offres_french_key(self, monkeypatch):
        """Cas limite : LLM envoie ``page_type: single`` avec une clé ``offres``
        au lieu de ``offer`` (erreur fréquente du LLM).
        Comportement actuel : le code ne gère que ``offer`` → erreur 422.
        C'est un cas documenté à corriger dans une version future."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "single",
                "offres": {"title": "Ingénieur Data"},
            }),
        )
        # Le code ne gère pas ce cas — une erreur est attendue
        # C'est un bug documenté : la clé ``offres`` n'est supportée qu'en ``list``
        with pytest.raises((LLMExtractionError, URLScrapingError)):
            extract_page("some text")


class TestMissingPageType:
    """Réponse LLM sans ``page_type`` explicite."""

    def test_dict_without_page_type_treated_as_single(self, monkeypatch):
        """Un dict d'offre sans ``page_type`` est traité comme ``single``."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "title": "Data Engineer",
                "company": "Acme",
                "location": "Paris",
                "contract_type": "CDI",
                "description": "Python SQL",
            }),
        )
        page = extract_page("some text")
        assert page.page_type == "single"
        assert page.offer is not None
        assert page.offer.get("title") == "Data Engineer"

    def test_empty_response_raises_error(self, monkeypatch):
        """Une réponse vide lève une erreur."""
        _mock_llm(monkeypatch, "{}")
        with pytest.raises((LLMExtractionError, URLScrapingError)):
            extract_page("some text")


class TestTruncatedResponse:
    """Réponse LLM tronquée (finish_reason = length)."""

    def test_truncated_json_raises_llm_extraction_error(self, monkeypatch):
        """Une réponse tronquée (finish_reason=length) lève LLMExtractionError."""
        _mock_llm(
            monkeypatch,
            '{"page_type": "list", "offres": [{"url": "https://',
            finish_reason="length",
        )
        with pytest.raises(LLMExtractionError, match="tronquée"):
            extract_page("some text")

    def test_truncated_without_finish_reason_still_raises(self, monkeypatch):
        """Même sans finish_reason explicite, un JSON invalide lève LLMExtractionError."""
        _mock_llm(
            monkeypatch,
            '{"page_type": "list", "offres": [',
            finish_reason="stop",
        )
        with pytest.raises(LLMExtractionError):
            extract_page("some text")


class TestExtractOffer:
    """Tests de ``extract_offer`` (mono-offre)."""

    def test_extract_offer_rejects_list_page(self, monkeypatch):
        """``extract_offer`` (mono-offre) rejette une page de type ``list``
        — une liste n'est pas une offre unique exploitable."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "list",
                "offres": [
                    {"url": "https://example.com/job/1"},
                ],
            }),
        )
        with pytest.raises(URLScrapingError):
            extract_offer("some text")

    def test_extract_offer_accepts_single_page(self, monkeypatch):
        """``extract_offer`` accepte une page de type ``single``."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "single",
                "offer": {
                    "title": "Data Engineer",
                    "company": "Acme",
                    "location": "Paris",
                    "contract_type": "CDI",
                    "description": "Python SQL",
                },
            }),
        )
        offer = extract_offer("some text")
        assert offer["title"] == "Data Engineer"
        assert offer["company"] == "Acme"

    def test_extract_offer_rejects_none_page_type(self, monkeypatch):
        """``extract_offer`` rejects a page with ``page_type: "none"``."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "none",
                "reason": "l'offre n'est plus disponible sur le site",
            }),
        )
        with pytest.raises(URLScrapingError, match="offre n'est plus disponible"):
            extract_offer("some text")


class TestEmptyAndNullFields:
    """Champs null ou absents dans la réponse LLM."""

    def test_missing_offer_field_raises(self, monkeypatch):
        """Réponse single sans le champ ``offer`` lève une erreur."""
        _mock_llm(
            monkeypatch,
            json.dumps({"page_type": "single"}),
        )
        with pytest.raises((LLMExtractionError, URLScrapingError)):
            extract_offer("some text")

    def test_null_title_in_offer_rejected(self, monkeypatch):
        """Un titre ``None`` est invalide (le titre est obligatoire) — l'extraction
        lève une erreur."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "single",
                "offer": {
                    "title": None,
                    "company": "Acme",
                    "location": "Paris",
                    "contract_type": "CDI",
                    "description": "Python SQL",
                },
            }),
        )
        with pytest.raises(URLScrapingError):
            extract_offer("some text")

    def test_extra_fields_ignored(self, monkeypatch):
        """Des champs supplémentaires dans la réponse sont ignorés."""
        _mock_llm(
            monkeypatch,
            json.dumps({
                "page_type": "single",
                "offer": {
                    "title": "Data Engineer",
                    "company": "Acme",
                    "location": "Paris",
                    "contract_type": "CDI",
                    "description": "Python SQL",
                    "unknown_field": "should be ignored",
                },
            }),
        )
        offer = extract_offer("some text")
        assert "unknown_field" not in offer
