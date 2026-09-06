"""Tests unitaires pour les modèles ORM."""
import pytest
from unittest.mock import MagicMock, patch


class TestCandidateProfileModel:
    """Tests de CandidateProfileModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        model = CandidateProfileModel(
            profile_name="test",
            headline="Data Engineer",
            summary="Expérimenté",
            skills=["python", "sql"],
            experiences=[{"title": "Dev"}],
            education=["Bac +5"],
            is_active=True,
            cv_raw_json={"raw_content": "# Test"},
        )

        assert model.profile_name == "test"
        assert model.headline == "Data Engineer"


class TestCvVersionModel:
    """Tests de CVVersionModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.cv_version import CVVersionModel

        model = CVVersionModel(
            id=1,
            job_offer_id=10,
            candidate_profile_id=20,
            match_result_id=30,
            cv_content_json={"markdown": "# Test"},
            cv_text="# Test",
            tailoring_notes=[],
            application_submitted=False,
        )

        assert model.job_offer_id == 10
        assert model.candidate_profile_id == 20
        assert model.application_submitted is False


class TestLetterVersionModel:
    """Tests de LetterVersionModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.letter_version import LetterVersionModel

        model = LetterVersionModel(
            id=1,
            job_offer_id=10,
            candidate_profile_id=20,
            match_result_id=30,
            letter_content_json={"markdown": "Madame, Monsieur"},
            letter_text="Madame, Monsieur",
        )

        assert model.job_offer_id == 10
        assert model.candidate_profile_id == 20


class TestJobOfferModel:
    """Tests de JobOfferModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.job_offer import JobOfferModel

        model = JobOfferModel(
            id=1,
            source="hellowork",
            source_job_id="123",
            url="https://example.com/job/123",
            title="Data Engineer",
            company="Acme",
            location="Paris",
            contract_type="CDI",
            published_date=None,
            experience="3 ans",
            diploma="Bac +5",
            description="Python SQL",
            skills_extracted=["python", "sql"],
            archived=False,
            raw_payload={},
            content_hash="abc",
        )

        assert model.source == "hellowork"
        assert model.title == "Data Engineer"
        assert model.archived is False


class TestMatchResultModel:
    """Tests de MatchResultModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.match_result import MatchResultModel

        model = MatchResultModel(
            id=1,
            job_offer_id=10,
            candidate_profile_id=20,
            total_score=75.0,
            score_breakdown={"title_score": 0.8},
            strengths=["Python"],
            weaknesses=["Databricks"],
            missing_skills=["databricks"],
            explanation="Test",
        )

        assert model.total_score == 75.0
        assert model.strengths == ["Python"]


class TestSearchParameterModel:
    """Tests de SearchParameterModel."""

    def test_model_creation(self):
        from src.infrastructure.db.models.search_parameters import SearchParameterModel

        model = SearchParameterModel(
            id=1,
            title="Data Engineer Paris",
            source="hellowork",
            url="https://hellowork.com/jobs/data-engineer",
            max_offers=5,
            is_active=True,
        )

        assert model.title == "Data Engineer Paris"
        assert model.max_offers == 5
        assert model.is_active is True


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class TestCandidateProfileDomain:
    """Tests du domaine CandidateProfile."""

    def test_profile_creation(self):
        from src.core.domain.candidate_profile import CandidateProfile

        profile = CandidateProfile(
            profile_name="test",
            headline="Data Engineer",
            summary="Expérimenté",
            skills=["python", "sql"],
            experiences=[{"title": "Dev"}],
            education=["Bac +5"],
            source_path="cv.md",
        )

        assert profile.profile_name == "test"
        assert profile.headline == "Data Engineer"

    def test_profile_to_dict(self):
        from src.core.domain.candidate_profile import CandidateProfile

        profile = CandidateProfile(
            profile_name="test",
            headline="Data Engineer",
            summary="Expérimenté",
            skills=["python"],
            experiences=[],
            education=[],
            source_path="cv.md",
        )

        d = profile.to_persist_dict()

        assert d["profile_name"] == "test"
        assert d["headline"] == "Data Engineer"
        assert d["skills"] == ["python"]


class TestJobOfferDomain:
    """Tests du domaine JobOffer."""

    def test_job_offer_creation(self):
        from src.core.domain.job_offer import JobOffer

        offer = JobOffer(
            id="123",
            source="hellowork",
            url="https://example.com",
            title="Data Engineer",
            company="Acme",
            localisation="Paris",
            contract_type="CDI",
            description="Python SQL",
            time_posted=None,
            contract_length="",
        )

        assert offer.id == "123"
        assert offer.title == "Data Engineer"
        assert offer.diploma == []

    def test_job_offer_to_dict(self):
        from src.core.domain.job_offer import JobOffer

        offer = JobOffer(
            id="123",
            source="hellowork",
            url="https://example.com",
            title="Data Engineer",
            company="Acme",
            localisation="Paris",
            contract_type="CDI",
            description="Python SQL",
            time_posted=None,
            contract_length="",
        )

        d = offer.to_dict()

        assert d["id"] == "123"
        assert d["title"] == "Data Engineer"
        assert d["source"] == "hellowork"
        assert d["diploma"] == []
