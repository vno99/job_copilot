"""Tests de l'extraction de compétences par LLM et de l'aplatissement."""

from types import SimpleNamespace

from src.core.scoring import score_engine
from src.core.scoring.score_engine import skills_to_names


def test_skills_to_names_flattens_hard_and_soft():
    skills = {
        "hard_skills": [
            {"name": "Python", "category": "langage", "level": "expert", "mandatory": True},
            {"name": "SQL", "category": "langage", "level": "maîtrise", "mandatory": True},
        ],
        "soft_skills": [{"name": "Travail en équipe", "category": "soft_skill"}],
        "certifications": [{"name": "AWS Certified Developer"}],
    }
    # Les certifications sont exclues du matching.
    assert skills_to_names(skills) == ["python", "sql", "travail en équipe"]


def test_skills_to_names_deduplicates_and_normalizes():
    skills = {
        "hard_skills": [
            {"name": "  Python ", "category": "langage"},
            {"name": "python", "category": "langage"},
        ],
        "soft_skills": [],
        "certifications": [],
    }
    assert skills_to_names(skills) == ["python"]


def test_skills_to_names_handles_missing_keys():
    assert skills_to_names({}) == []
    assert skills_to_names(None) == []
    assert (
        skills_to_names({"hard_skills": [], "soft_skills": [], "certifications": []})
        == []
    )


def test_extract_skills_parses_llm_response(monkeypatch):
    raw = """```json
    {"hard_skills": [{"name": "Python", "category": "langage", "level": "expert", "mandatory": true}],
     "soft_skills": [], "certifications": []}
    ```"""
    monkeypatch.setattr(
        score_engine,
        "LLM",
        SimpleNamespace(invoke=lambda _messages: SimpleNamespace(content=raw)),
    )
    result = score_engine.extract_skills("Python")
    assert result["hard_skills"][0]["name"] == "Python"
    assert result["hard_skills"][0]["mandatory"] is True
    assert result["soft_skills"] == []
    assert result["certifications"] == []
    # Extraction réussie avec compétences trouvées.
    assert result["_status"] == "extracted"


def test_extract_skills_defaults_missing_keys(monkeypatch):
    monkeypatch.setattr(
        score_engine,
        "LLM",
        SimpleNamespace(invoke=lambda _messages: SimpleNamespace(content='{"hard_skills": []}')),
    )
    result = score_engine.extract_skills("rien")
    assert result["hard_skills"] == []
    assert result["soft_skills"] == []
    assert result["certifications"] == []
    # Extraction réussie, mais aucune compétence détectée dans le texte.
    assert result["_status"] == "empty"


def test_extract_skills_empty_when_no_api_key(monkeypatch):
    """Sans clé API : listes vides + ``_status="disabled"`` (le matching peut
    distinguer « LLM désactivé » d'une extraction réussie sans compétence)."""
    monkeypatch.setattr(score_engine, "LLM", None)
    result = score_engine.extract_skills("Python")
    assert result == {
        "hard_skills": [],
        "soft_skills": [],
        "certifications": [],
        "_status": "disabled",
    }


def test_extract_skills_failed_on_invalid_json(monkeypatch):
    """Réponse LLM invalide (JSON cassé) → ``_status="failed"``, pas ``"empty"`` :
    une ré-extraction est justifiée, alors qu'une offre sans compétence ne doit
    pas être retraitée."""
    monkeypatch.setattr(
        score_engine,
        "LLM",
        SimpleNamespace(
            invoke=lambda _messages: SimpleNamespace(content="pas du json du tout")
        ),
    )
    result = score_engine.extract_skills("Python")
    assert result["_status"] == "failed"
    assert result["hard_skills"] == []


def test_extract_skills_failed_on_api_exception(monkeypatch):
    """Exception réseau / API LLM → ``_status="failed"`` (vs ``"empty"``)."""

    class _BoomLLM:
        def invoke(self, _messages):
            raise RuntimeError("connexion refusée par l'API")

    monkeypatch.setattr(score_engine, "LLM", _BoomLLM())
    result = score_engine.extract_skills("Python")
    assert result["_status"] == "failed"


def test_offer_skills_uses_stored_value(monkeypatch):
    """Le stockage en base prime : extract_skills (LLM) ne doit pas être rappelé."""
    offer = {
        "description": "Python SQL",
        "skills_extracted": {
            "hard_skills": [{"name": "Python", "category": "langage", "level": "expert", "mandatory": True}],
            "soft_skills": [],
            "certifications": [],
        },
    }

    def _should_not_be_called(_text):
        raise AssertionError("extract_skills ne doit pas être rappelé si skills_extracted est stocké")

    monkeypatch.setattr(score_engine, "extract_skills", _should_not_be_called)
    assert score_engine.offer_skills(offer) == ["python"]


def test_offer_skills_respects_empty_stored(monkeypatch):
    """Un stockage vide ({} à l'ingestion) n'entraîne pas de re-extraction LLM."""
    offer = {"description": "Python", "skills_extracted": {}}

    def _should_not_be_called(_text):
        raise AssertionError("extract_skills ne doit pas être rappelé si skills_extracted est stocké")

    monkeypatch.setattr(score_engine, "extract_skills", _should_not_be_called)
    assert score_engine.offer_skills(offer) == []


def test_offer_skills_falls_back_when_not_stored():
    """Sans skills_extracted, on retombe sur l'extraction (LLM mocké en conftest)."""
    offer = {"description": "SQL"}
    assert score_engine.offer_skills(offer) == ["sql"]
