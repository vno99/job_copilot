"""Tests du matching LLM (src/core/scoring/llm_matcher.py)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Tests des fonctions internes et mocking (provenant de test_llm_matcher_unit.py)
# ---------------------------------------------------------------------------

class TestLlmMatcherFunctions:
    """Tests des fonctions pures de llm_matcher."""

    def test_strip_code_fences_empty(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        assert _strip_code_fences("") == ""
        assert _strip_code_fences(None) == ""

    def test_strip_code_fences_no_fences(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        text = '{"score": 75}'
        assert _strip_code_fences(text) == text

    def test_strip_code_fences_with_json_lang(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        text = '```json\n{"score": 75}\n```'
        assert _strip_code_fences(text) == '{"score": 75}'

    def test_strip_code_fences_with_markdown_lang(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        text = '```markdown\n## CV\n```'
        assert _strip_code_fences(text) == '## CV'

    def test_strip_code_fences_naked(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        text = '```\n{"score": 75}\n```'
        assert _strip_code_fences(text) == '{"score": 75}'

    def test_strip_code_fences_with_whitespace(self):
        from src.core.scoring.llm_matcher import _strip_code_fences

        text = '  ```json\n{"score": 75}\n```  '
        assert _strip_code_fences(text) == '{"score": 75}'

    def test_as_float_valid(self):
        from src.core.scoring.llm_matcher import _as_float

        assert _as_float(75) == 75.0
        assert _as_float(75.5) == 75.5
        assert _as_float("75") == 75.0
        assert _as_float("75.5") == 75.5

    def test_as_float_invalid(self):
        from src.core.scoring.llm_matcher import _as_float

        with pytest.raises(ValueError):
            _as_float("invalid")

    def test_as_str_list_valid(self):
        from src.core.scoring.llm_matcher import _as_str_list

        assert _as_str_list(["Python", "SQL"]) == ["Python", "SQL"]

    def test_as_str_list_empty(self):
        from src.core.scoring.llm_matcher import _as_str_list

        assert _as_str_list(None) == []
        assert _as_str_list([]) == []

    def test_as_str_list_with_empty_strings(self):
        from src.core.scoring.llm_matcher import _as_str_list

        result = _as_str_list(["python", "", "  ", "sql"])
        assert result == ["python", "sql"]

    def test_normalize_result_valid(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 75,
            "score_breakdown": {
                "title_score": 0.8,
                "skills_score": 0.7,
                "experience_score": 0.6,
                "education_score": 0.5,
            },
            "strengths": ["Python", "SQL"],
            "weaknesses": ["Databricks"],
            "missing_skills": ["databricks"],
            "explanation": "Test explanation",
        }

        result = _normalize_result(data)

        assert result["score"] == 75.0
        assert result["score_breakdown"]["title_score"] == 0.8
        assert result["strengths"] == ["Python", "SQL"]
        assert result["weaknesses"] == ["Databricks"]
        assert result["missing_skills"] == ["databricks"]
        assert result["explanation"] == "Test explanation"

    def test_normalize_result_scale_0_1(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 0.75,
            "score_breakdown": {
                "title_score": 0.8,
                "skills_score": 0.7,
                "experience_score": 0.6,
                "education_score": 0.5,
            },
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        result = _normalize_result(data)

        assert result["score"] == 75.0

    def test_normalize_result_missing_score(self):
        from src.core.scoring.llm_matcher import _normalize_result, LLMMatchingError

        data = {
            "score_breakdown": {},
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        with pytest.raises(LLMMatchingError, match="score"):
            _normalize_result(data)

    def test_normalize_result_invalid_score(self):
        from src.core.scoring.llm_matcher import _normalize_result, LLMMatchingError

        data = {
            "score": "invalid",
            "score_breakdown": {},
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        with pytest.raises(LLMMatchingError, match="score"):
            _normalize_result(data)

    def test_normalize_result_invalid_breakdown(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 75,
            "score_breakdown": "invalid",
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        result = _normalize_result(data)

        assert isinstance(result["score_breakdown"], dict)

    def test_normalize_result_breakdown_clamping(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 150,
            "score_breakdown": {
                "title_score": 1.5,
                "skills_score": -0.5,
                "experience_score": 0.6,
                "education_score": 0.5,
            },
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        result = _normalize_result(data)

        assert result["score"] == 100.0
        assert result["score_breakdown"]["title_score"] == 1.0
        assert result["score_breakdown"]["skills_score"] == 0.0

    def test_normalize_result_breakdown_invalid_values(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 75,
            "score_breakdown": {
                "title_score": "invalid",
                "skills_score": None,
                "experience_score": 0.6,
                "education_score": 0.5,
            },
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

        result = _normalize_result(data)

        assert result["score_breakdown"]["title_score"] == 0.0
        assert result["score_breakdown"]["skills_score"] == 0.0

    def test_normalize_result_explanation_none(self):
        from src.core.scoring.llm_matcher import _normalize_result

        data = {
            "score": 75,
            "score_breakdown": {},
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": None,
        }

        result = _normalize_result(data)

        assert result["explanation"] == ""


class TestComputeLlmMatchInternal:
    """Tests de compute_llm_match avec mock du LLM (version interne)."""

    def test_compute_llm_match_no_api_key(self, monkeypatch):
        from src.core.scoring.llm_matcher import compute_llm_match, LLMMatchingError
        from src.core.scoring import score_engine

        monkeypatch.setattr(score_engine, "LLM", None)

        with pytest.raises(LLMMatchingError, match="OPENROUTER_API_KEY"):
            compute_llm_match({"title": "Dev"}, {"raw_cv": "Python SQL"})

    def test_compute_llm_match_success(self, monkeypatch):
        from src.core.scoring.llm_matcher import compute_llm_match
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(
            content='{"score": 75, "score_breakdown": {"title_score": 0.8, "skills_score": 0.7, "experience_score": 0.6, "education_score": 0.5}, "strengths": ["Python"], "weaknesses": [], "missing_skills": [], "explanation": "Test"}'
        )
        monkeypatch.setattr(score_engine, "LLM", mock_llm)

        result = compute_llm_match(
            {"title": "Dev", "description": "Python SQL"},
            {"raw_cv": "# Jean\nPython SQL"}
        )

        assert result["score"] == 75.0
        assert "score_breakdown" in result

    def test_compute_llm_match_response_not_dict(self, monkeypatch):
        from src.core.scoring.llm_matcher import compute_llm_match, LLMMatchingError
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(content='[1, 2, 3]')
        monkeypatch.setattr(score_engine, "LLM", mock_llm)

        with pytest.raises(LLMMatchingError, match="JSON non-objet"):
            compute_llm_match({"title": "Dev"}, {"raw_cv": "Python"})

    def test_compute_llm_match_invalid_json(self, monkeypatch):
        from src.core.scoring.llm_matcher import compute_llm_match, LLMMatchingError
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(content='not json {')
        monkeypatch.setattr(score_engine, "LLM", mock_llm)

        with pytest.raises(LLMMatchingError, match="JSON invalide"):
            compute_llm_match({"title": "Dev"}, {"raw_cv": "Python"})

    def test_compute_llm_match_api_error(self, monkeypatch):
        from src.core.scoring.llm_matcher import compute_llm_match, LLMMatchingError
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API down")
        monkeypatch.setattr(score_engine, "LLM", mock_llm)

        with pytest.raises(LLMMatchingError, match="erreur API"):
            compute_llm_match({"title": "Dev"}, {"raw_cv": "Python"})

    def test_compute_llm_match_truncates_long_description(self, monkeypatch):
        from src.core.scoring.llm_matcher import _build_prompt, MAX_DESCRIPTION_CHARS
        from src.core.scoring import score_engine

        long_description = "x" * (MAX_DESCRIPTION_CHARS + 1000)
        job = {"title": "Dev", "description": long_description}

        prompt = _build_prompt(job, {"raw_cv": "short cv"})

        assert len(job["description"]) > MAX_DESCRIPTION_CHARS
        assert "…" in prompt or prompt.endswith("…")

    def test_compute_llm_match_truncates_long_cv(self, monkeypatch):
        from src.core.scoring.llm_matcher import _build_prompt, MAX_CV_CHARS
        from src.core.scoring import score_engine

        job = {"title": "Dev", "description": "short"}
        long_cv = "x" * (MAX_CV_CHARS + 1000)

        prompt = _build_prompt(job, {"raw_cv": long_cv})

        assert "…" in prompt or prompt.endswith("…")


class TestBuildPromptInternal:
    """Tests de _build_prompt (version interne)."""

    def test_build_prompt_contains_markers(self):
        from src.core.scoring.llm_matcher import _build_prompt, JOB_MARKER, PROFILE_MARKER

        job = {"title": "Dev", "description": "Python SQL"}
        profile = {"raw_cv": "# Jean\nPython SQL"}

        prompt = _build_prompt(job, profile)

        assert JOB_MARKER in prompt
        assert PROFILE_MARKER in prompt
        assert "Dev" in prompt

    def test_build_prompt_empty_fields(self):
        from src.core.scoring.llm_matcher import _build_prompt

        job = {"title": "", "description": ""}
        profile = {"raw_cv": ""}

        prompt = _build_prompt(job, profile)

        assert prompt is not None
        assert "PROFIL CANDIDAT" in prompt
