#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests unitaires pour job_analysis."""

import pytest
from unittest.mock import MagicMock, patch


def test_diploma_to_list_with_duplicates():
    """_diploma_to_list deduplique tout en preservant l'ordre."""
    from src.services.job_analysis import _diploma_to_list
    result = _diploma_to_list("Bac+3, Bac+3, Bac+5, Bac+5")
    assert result == ["Bac+3", "Bac+5"]


def test_diploma_to_list_with_spaces():
    """_diploma_to_list nettoie les espaces autour des virgules."""
    from src.services.job_analysis import _diploma_to_list
    result = _diploma_to_list("Bac+3,  Bac+5 ,  Bac+5")
    assert result == ["Bac+3", "Bac+5"]


def test_diploma_to_list_empty():
    """_diploma_to_list renvoie [] pour valeur None ou vide."""
    from src.services.job_analysis import _diploma_to_list
    assert _diploma_to_list(None) == []
    assert _diploma_to_list("") == []
    assert _diploma_to_list("   ") == []


def test_build_score_job_with_diploma_list():
    """build_score_job renvoie la liste de diplomes (pas une chaine)."""
    from src.services.job_analysis import build_score_job
    from src.infrastructure.db.models.job_offer import JobOfferModel

    mock_row = MagicMock(spec=JobOfferModel)
    mock_row.title = "Dev"
    mock_row.company = "Acme"
    mock_row.location = "Paris"
    mock_row.contract_type = "CDI"
    mock_row.experience = "3 ans"
    mock_row.diploma = "Bac+3, Bac+5"
    mock_row.description = "Developpement Python"
    mock_row.skills_extracted = ["Python"]

    result = build_score_job(mock_row)

    assert result["diploma"] == ["Bac+3", "Bac+5"]
    assert result["title"] == "Dev"
    assert result["experience"] == "3 ans"


def test_build_score_job_empty_fields():
    """build_score_job gere les champs None ou vides."""
    from src.services.job_analysis import build_score_job
    from src.infrastructure.db.models.job_offer import JobOfferModel

    mock_row = MagicMock(spec=JobOfferModel)
    mock_row.title = None
    mock_row.company = None
    mock_row.location = None
    mock_row.contract_type = None
    mock_row.experience = None
    mock_row.diploma = None
    mock_row.description = None
    mock_row.skills_extracted = None

    result = build_score_job(mock_row)

    assert result["title"] == ""
    assert result["company"] == ""
    assert result["diploma"] == []
    assert result["skills_extracted"] is None


def test_build_score_profile_with_raw_content(monkeypatch):
    """build_score_profile passe raw_cv au matching."""
    from src.services.job_analysis import build_score_profile
    from src.core.domain.candidate_profile import CandidateProfile

    profile = MagicMock(spec=CandidateProfile)
    profile.headline = "Jean Dupont"

    # Du texte Markdown
    raw_content = "# Jean\\n\\n## Skills\\n- Python"
    result = build_score_profile(profile, raw_content)

    assert "raw_cv" in result
    # Anonymise : le nom ne doit pas apparaitre tel quel
    assert "[NOM]" in result["raw_cv"] or "Jean" not in result["raw_cv"]


def test_build_score_profile_empty_content():
    """build_score_profile fonctionne meme sans raw_content."""
    from src.services.job_analysis import build_score_profile
    from src.core.domain.candidate_profile import CandidateProfile

    profile = MagicMock(spec=CandidateProfile)
    profile.headline = "Jean"

    result = build_score_profile(profile, "")

    assert "raw_cv" in result


def test_job_analysis_service_run_uses_raw_content(monkeypatch):
    """run() passe le raw_content du profil au matching."""
    from src.services.job_analysis import JobAnalysisService
    from src.infrastructure.db.models.job_offer import JobOfferModel
    from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
    from src.infrastructure.db.repositories import match_result_repository
    from src.core.domain.candidate_profile import CandidateProfile
    from src.core.scoring import llm_matcher

    mock_job_row = MagicMock(spec=JobOfferModel)
    mock_job_row.title = "Dev"
    mock_job_row.company = "Acme"
    mock_job_row.location = "Paris"
    mock_job_row.contract_type = "CDI"
    mock_job_row.experience = ""
    mock_job_row.diploma = None
    mock_job_row.description = "Python"
    mock_job_row.skills_extracted = []

    mock_profile_row = MagicMock(spec=CandidateProfileModel)
    mock_profile_row.profile_name = "Test"
    mock_profile_row.headline = "Jean"
    mock_profile_row.summary = None
    mock_profile_row.skills = []
    mock_profile_row.experiences = []
    mock_profile_row.education = []
    mock_profile_row.source_path = ""
    mock_profile_row.is_active = True
    mock_profile_row.cv_raw_json = {"raw_content": "# Jean\\n\\n## Skills\\n- Python"}

    captured_profile_dict = {}

    def fake_compute_llm_match(job_dict, profile_dict):
        captured_profile_dict["raw_cv"] = profile_dict.get("raw_cv", "")
        return {
            "score": 75.0,
            "score_breakdown": {},
            "strengths": [],
            "weaknesses": [],
            "missing_skills": [],
            "explanation": "",
        }

    mock_session = MagicMock()
    def get_mock(model, id):
        if model == JobOfferModel:
            return mock_job_row
        return mock_profile_row
    mock_session.get.side_effect = get_mock

    class FakeScope:
        def __enter__(self):
            return mock_session
        def __exit__(self, *a):
            pass

    with patch(
        "src.services.job_analysis.session_scope",
        return_value=FakeScope()
    ):
        with patch.object(match_result_repository, "upsert", return_value=42):
            with patch(
                "src.services.job_analysis.compute_llm_match",
                side_effect=fake_compute_llm_match
            ):
                service = JobAnalysisService()
                service.run(1, 1)

    # Le raw_content a ete passe au matching
    assert "raw_cv" in captured_profile_dict


def test_job_analysis_service_raises_on_missing_job():
    """run() leve ValueError si l'offre n'existe pas."""
    from src.services.job_analysis import JobAnalysisService
    from src.infrastructure.db.models.job_offer import JobOfferModel
    from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

    mock_session = MagicMock()
    mock_session.get.side_effect = lambda model, id: None

    class FakeScope:
        def __enter__(self):
            return mock_session
        def __exit__(self, *a):
            pass

    with patch(
        "src.services.job_analysis.session_scope",
        return_value=FakeScope()
    ):
        service = JobAnalysisService()
        with pytest.raises(ValueError, match="introuvable"):
            service.run(999, 1)


def test_job_analysis_service_raises_on_missing_profile():
    """run() leve ValueError si le profil n'existe pas."""
    from src.services.job_analysis import JobAnalysisService
    from src.infrastructure.db.models.job_offer import JobOfferModel
    from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

    mock_job_row = MagicMock(spec=JobOfferModel)
    mock_session = MagicMock()

    def get_mock(model, id):
        if model == JobOfferModel:
            return mock_job_row
        return None
    mock_session.get.side_effect = get_mock

    class FakeScope:
        def __enter__(self):
            return mock_session
        def __exit__(self, *a):
            pass

    with patch(
        "src.services.job_analysis.session_scope",
        return_value=FakeScope()
    ):
        service = JobAnalysisService()
        with pytest.raises(ValueError, match="introuvable"):
            service.run(1, 999)
