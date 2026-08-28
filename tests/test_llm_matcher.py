"""Tests du matching LLM (src/core/scoring/llm_matcher.py)."""

import json
from types import SimpleNamespace

import pytest

from src.core.scoring import score_engine
from src.core.scoring.llm_matcher import (
    BREAKDOWN_KEYS,
    LLMMatchingError,
    compute_llm_match,
)


def _job_dict():
    return {
        "title": "Data Engineer",
        "company": "Alfi",
        "location": "Paris",
        "contract_type": "CDI",
        "experience": "3 ans",
        "diploma": ["Bac +5"],
        "description": "Python SQL Databricks pour des pipelines de données.",
        "skills_extracted": {
            "hard_skills": [{"name": "Python"}],
            "soft_skills": [],
            "certifications": [],
        },
    }


def _profile_dict():
    return {
        "raw_cv": (
            "Jean Dupont\n"
            "Data Engineer senior\n"
            "Compétences : Python, SQL, Databricks\n"
            "Data Engineer — Acme (2020 - 2024) : Pipelines Airflow et Spark\n"
            "Formation : Master Informatique"
        ),
    }


def _valid_payload(**overrides):
    payload = {
        "score": 72,
        "score_breakdown": {
            "title_score": 0.9,
            "skills_score": 0.6,
            "experience_score": 0.8,
            "education_score": 0.5,
        },
        "strengths": ["Maîtrise de Python et SQL"],
        "weaknesses": ["Pas d'expérience Databricks"],
        "missing_skills": ["databricks"],
        "explanation": "Mettez en avant vos pipelines Airflow.",
    }
    payload.update(overrides)
    return payload


def _mock_llm(monkeypatch, raw: str) -> None:
    monkeypatch.setattr(
        score_engine,
        "LLM",
        SimpleNamespace(invoke=lambda _messages: SimpleNamespace(content=raw)),
    )


def test_compute_llm_match_parses_valid_response(monkeypatch):
    _mock_llm(monkeypatch, json.dumps(_valid_payload(), ensure_ascii=False))
    result = compute_llm_match(_job_dict(), _profile_dict())
    assert result["score"] == 72.0
    assert set(result["score_breakdown"]) == set(BREAKDOWN_KEYS)
    assert result["strengths"] == ["Maîtrise de Python et SQL"]
    assert result["missing_skills"] == ["databricks"]
    assert "Airflow" in result["explanation"]


def test_compute_llm_match_strips_code_fences(monkeypatch):
    raw = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    _mock_llm(monkeypatch, raw)
    result = compute_llm_match(_job_dict(), _profile_dict())
    assert result["score"] == 72.0


def test_compute_llm_match_clamps_score_and_breakdown(monkeypatch):
    _mock_llm(
        monkeypatch,
        json.dumps(
            _valid_payload(
                score=150,
                score_breakdown={"title_score": 2.5, "skills_score": -1, "education_score": "0.5"},
            )
        ),
    )
    result = compute_llm_match(_job_dict(), _profile_dict())
    assert result["score"] == 100.0
    assert result["score_breakdown"]["title_score"] == 1.0
    assert result["score_breakdown"]["skills_score"] == 0.0
    # Clé absente du breakdown -> 0.0, pas d'erreur.
    assert result["score_breakdown"]["experience_score"] == 0.0
    assert result["score_breakdown"]["education_score"] == 0.5


def test_compute_llm_match_defaults_missing_keys(monkeypatch):
    _mock_llm(monkeypatch, '{"score": 40, "score_breakdown": {}}')
    result = compute_llm_match(_job_dict(), _profile_dict())
    assert result["score"] == 40.0
    assert result["strengths"] == []
    assert result["weaknesses"] == []
    assert result["missing_skills"] == []
    assert result["explanation"] == ""


def test_compute_llm_match_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(score_engine, "LLM", None)
    with pytest.raises(LLMMatchingError):
        compute_llm_match(_job_dict(), _profile_dict())


def test_compute_llm_match_raises_on_malformed_json(monkeypatch):
    _mock_llm(monkeypatch, "pas du json valide")
    with pytest.raises(LLMMatchingError):
        compute_llm_match(_job_dict(), _profile_dict())


def test_compute_llm_match_raises_on_missing_score(monkeypatch):
    _mock_llm(monkeypatch, '{"score_breakdown": {}, "strengths": []}')
    with pytest.raises(LLMMatchingError):
        compute_llm_match(_job_dict(), _profile_dict())


def test_compute_llm_match_raises_on_api_error(monkeypatch):
    def _boom(_messages):
        raise ConnectionError("réseau coupé")

    monkeypatch.setattr(
        score_engine, "LLM", SimpleNamespace(invoke=_boom)
    )
    with pytest.raises(LLMMatchingError):
        compute_llm_match(_job_dict(), _profile_dict())


def test_build_prompt_contains_job_and_profile(monkeypatch):
    """Le prompt transmet bien les deux marqueurs et le contenu profil/offre."""
    from src.core.scoring.llm_matcher import _build_prompt

    prompt = _build_prompt(_job_dict(), _profile_dict())
    assert "=== OFFRE D'EMPLOI ===" in prompt
    assert "=== PROFIL CANDIDAT ===" in prompt
    assert '"title": "Data Engineer"' in prompt
    assert '"raw_cv"' in prompt
    assert "Jean Dupont" in prompt
    # Le CV anonymisé est signalé au LLM.
    assert "anonymisé" in prompt
    # La description longue est bornée.
    long_job = dict(_job_dict())
    long_job["description"] = "x" * 10_000
    assert len(_build_prompt(long_job, _profile_dict())) < 10_000


def test_build_prompt_truncates_long_cv():
    """Un CV très long est tronqué (borne MAX_CV_CHARS)."""
    from src.core.scoring.llm_matcher import _build_prompt

    long_profile = {"raw_cv": "x" * 20_000}
    prompt = _build_prompt(_job_dict(), long_profile)
    assert len(prompt) < 20_000
    assert '"raw_cv"' in prompt
