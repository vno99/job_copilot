"""Tests unitaires (hors DB) pour les services.

Ces tests ne nécessitent pas de base de données : les services sont testés
en mockant `session_scope` et les dépendances DB.
"""
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# job_parser
# ---------------------------------------------------------------------------

class TestJobParserFunctions:
    """Tests des fonctions pures de job_parser (pas de sessionScope)."""

    def test_parse_published_date_none(self):
        from src.services.job_parser import _parse_published_date
        assert _parse_published_date(None) is None
        assert _parse_published_date("") is None

    def test_parse_published_date_already_date(self):
        from datetime import date
        from src.services.job_parser import _parse_published_date
        d = date(2024, 1, 15)
        assert _parse_published_date(d) == d

    def test_parse_published_date_ddmmyyyy(self):
        from src.services.job_parser import _parse_published_date
        assert _parse_published_date("15/01/2024") == __import__("datetime").date(2024, 1, 15)

    def test_parse_published_date_iso(self):
        from src.services.job_parser import _parse_published_date
        assert _parse_published_date("2024-01-15") == __import__("datetime").date(2024, 1, 15)

    def test_parse_published_date_invalid(self):
        from src.services.job_parser import _parse_published_date
        assert _parse_published_date("invalide") is None

    def test_diploma_to_text_none(self):
        from src.services.job_parser import _diploma_to_text
        assert _diploma_to_text(None) is None

    def test_diploma_to_text_list(self):
        from src.services.job_parser import _diploma_to_text
        assert _diploma_to_text(["Bac +3", "Bac +5"]) == "Bac +3, Bac +5"

    def test_diploma_to_text_string(self):
        from src.services.job_parser import _diploma_to_text
        assert _diploma_to_text("Bac +3") == "Bac +3"

    def test_diploma_to_text_empty_string(self):
        from src.services.job_parser import _diploma_to_text
        assert _diploma_to_text("   ") is None

    def test_compute_content_hash(self):
        from src.services.job_parser import _compute_content_hash
        h1 = _compute_content_hash({"a": 1, "b": 2})
        h2 = _compute_content_hash({"b": 2, "a": 1})
        assert h1 == h2  # Clés triées = empreinte stable

    def test_normalize_job_offer(self):
        from datetime import date
        from src.services.job_parser import normalize_job_offer
        from src.core.domain.job_offer import JobOffer

        offer = JobOffer(
            id="123",
            source="hellowork",
            url="https://example.com/job/123",
            title="  Data Engineer  ",
            company="  Acme  ",
            localisation="  Paris  ",
            contract_type="CDI",
            description="Python SQL",
            published_date="2024-01-15",
            experience="3 ans",
            diploma="Bac +5",
            time_posted=None,
            contract_length="",
        )
        normalized = normalize_job_offer(offer)
        assert normalized["source"] == "hellowork"
        assert normalized["source_job_id"] == "123"
        assert normalized["title"] == "Data Engineer"
        assert normalized["company"] == "Acme"
        assert normalized["location"] == "Paris"
        assert normalized["published_date"] == date(2024, 1, 15)
        assert normalized["diploma"] == "Bac +5"
        assert "content_hash" in normalized

    def test_normalize_job_offer_with_list_diploma(self):
        from src.services.job_parser import normalize_job_offer
        from src.core.domain.job_offer import JobOffer

        offer = JobOffer(
            id="456",
            source="test",
            url="https://example.com/job/456",
            title="Dev",
            company="TestCorp",
            localisation="Lyon",
            contract_type="CDI",
            description="Python",
            diploma=["Bac +3", "Bac +4"],
            time_posted=None,
            contract_length="",
        )
        normalized = normalize_job_offer(offer)
        assert normalized["diploma"] == "Bac +3, Bac +4"


class TestJobParserServiceRun:
    """Tests de JobParserService.run avec mock de session_scope."""

    def test_run_nonexistent_dir(self, monkeypatch):
        from src.services.job_parser import JobParserService
        from pathlib import Path

        fake_dir = MagicMock(spec=Path)
        fake_dir.exists.return_value = False

        with patch("src.services.job_parser.HELLOWORK_OUTPUT_DIR", fake_dir):
            service = JobParserService()
            result = service.run(output_dir=fake_dir)
            assert result == {"ingested": 0, "updated": 0, "unchanged": 0}

    def test_run_no_json_files(self, monkeypatch, tmp_path):
        from src.services.job_parser import JobParserService

        service = JobParserService()
        result = service.run(output_dir=tmp_path)
        assert result == {"ingested": 0, "updated": 0, "unchanged": 0}

    def test_run_with_mocked_session(self, monkeypatch, tmp_path):
        from src.services.job_parser import JobParserService

        # Crée un faux fichier JSON
        import json
        fake_job = {
            "id": "test_001",
            "source": "hellowork",
            "url": "https://example.com/job/test_001",
            "title": "Data Engineer",
            "company": "Acme",
            "localisation": "Paris",
            "contract_type": "CDI",
            "description": "Python SQL",
        }
        json_path = tmp_path / "job_001.json"
        json_path.write_text(json.dumps(fake_job), encoding="utf-8")

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(rowcount=1)

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.job_parser.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.job_parser.HELLOWORK_OUTPUT_DIR", tmp_path)

        service = JobParserService()
        result = service.run()

        assert "ingested" in result
        assert "updated" in result
        assert "unchanged" in result


# ---------------------------------------------------------------------------
# job_analysis
# ---------------------------------------------------------------------------

class TestJobAnalysisFunctions:
    """Tests des fonctions pures de job_analysis."""

    def test_diploma_to_list_empty(self):
        from src.services.job_analysis import _diploma_to_list
        assert _diploma_to_list(None) == []
        assert _diploma_to_list("") == []

    def test_diploma_to_list_single(self):
        from src.services.job_analysis import _diploma_to_list
        assert _diploma_to_list("Bac +5") == ["Bac +5"]

    def test_diploma_to_list_multiple(self):
        from src.services.job_analysis import _diploma_to_list
        result = _diploma_to_list("Bac +3, Bac +4, Bac +5")
        assert result == ["Bac +3", "Bac +4", "Bac +5"]

    def test_diploma_to_list_with_spaces(self):
        from src.services.job_analysis import _diploma_to_list
        result = _diploma_to_list("  Bac +3  ,  Bac +5  ")
        assert result == ["Bac +3", "Bac +5"]

    def test_diploma_to_list_duplicates_removed(self):
        from src.services.job_analysis import _diploma_to_list
        result = _diploma_to_list("Bac +3, Bac +3, Bac +5")
        assert result == ["Bac +3", "Bac +5"]

    def test_build_score_job(self):
        from src.services.job_analysis import build_score_job
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from datetime import datetime

        mock_row = MagicMock(spec=JobOfferModel)
        mock_row.title = "Data Engineer"
        mock_row.company = "Acme"
        mock_row.location = "Paris"
        mock_row.contract_type = "CDI"
        mock_row.experience = "3 ans"
        mock_row.diploma = "Bac +5"
        mock_row.description = "Python SQL"
        mock_row.skills_extracted = ["python", "sql"]

        result = build_score_job(mock_row)
        assert result["title"] == "Data Engineer"
        assert result["company"] == "Acme"
        assert result["location"] == "Paris"
        assert result["contract_type"] == "CDI"
        assert result["experience"] == "3 ans"
        assert result["diploma"] == ["Bac +5"]
        assert result["description"] == "Python SQL"
        assert result["skills_extracted"] == ["python", "sql"]

    def test_build_score_job_with_csv_diploma(self):
        from src.services.job_analysis import build_score_job
        from src.infrastructure.db.models.job_offer import JobOfferModel

        mock_row = MagicMock(spec=JobOfferModel)
        mock_row.title = "Dev"
        mock_row.company = "Corp"
        mock_row.location = ""
        mock_row.contract_type = ""
        mock_row.experience = ""
        mock_row.diploma = "Bac +3, Bac +4, Bac +5"
        mock_row.description = ""
        mock_row.skills_extracted = []

        result = build_score_job(mock_row)
        assert result["diploma"] == ["Bac +3", "Bac +4", "Bac +5"]

    def test_build_score_profile(self):
        from src.services.job_analysis import build_score_profile
        from src.core.domain.candidate_profile import CandidateProfile

        profile = CandidateProfile(
            profile_name="test",
            headline="Data Engineer",
            summary=None,
            skills=[],
            experiences=[],
            education=[],
            source_path="cv.md",
        )

        result = build_score_profile(profile, raw_content="# Data Engineer\n\n## Compétences\n- Python")
        assert "raw_cv" in result
        # Le headline "Data Engineer" est utilisé comme nom pour l'anonymisation
        # Mais sans vrai nom, l'anonymisation ne fait rien sur ce texte
        assert isinstance(result["raw_cv"], str)


class TestJobAnalysisServiceRun:
    """Tests de JobAnalysisService.run avec mock de session_scope."""

    def test_run_offre_not_found(self, monkeypatch):
        from src.services.job_analysis import JobAnalysisService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        mock_session.get.side_effect = lambda model, id: None

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.job_analysis.session_scope", mock_session_scope)

        service = JobAnalysisService()
        with pytest.raises(ValueError, match="introuvable"):
            service.run(1, 1)

    def test_run_profil_not_found(self, monkeypatch):
        from src.services.job_analysis import JobAnalysisService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        # Simule offre trouvée mais profil non trouvé
        def get_side_effect(model, id):
            if model == JobOfferModel:
                return MagicMock(title="Dev", company="Corp")
            return None
        mock_session.get.side_effect = get_side_effect

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.job_analysis.session_scope", mock_session_scope)

        service = JobAnalysisService()
        with pytest.raises(ValueError, match="introuvable"):
            service.run(1, 1)


# ---------------------------------------------------------------------------
# cv_generator
# ---------------------------------------------------------------------------

class TestCvGeneratorServiceRun:
    """Tests de CvGeneratorService.run avec mock de session_scope."""

    def test_run_offre_not_found(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService

        mock_session = MagicMock()
        mock_session.get.return_value = None

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)

        service = CvGeneratorService()
        with pytest.raises(ValueError, match="Offre.*introuvable"):
            service.run(1, 1)

    def test_run_profil_not_found(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        def get_side_effect(model, id):
            if model == JobOfferModel:
                return MagicMock(title="Dev")
            return None
        mock_session.get.side_effect = get_side_effect

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)

        service = CvGeneratorService()
        with pytest.raises(ValueError, match="Profil.*introuvable"):
            service.run(1, 1)

    def test_run_no_match_result(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService, CvRequiresMatchError
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        mock_job = MagicMock(title="Dev", company="Corp")
        mock_profile = MagicMock(profile_name="test")

        def get_side_effect(model, id):
            if model == JobOfferModel:
                return mock_job
            if model == CandidateProfileModel:
                return mock_profile
            return None
        mock_session.get.side_effect = get_side_effect

        mock_match_repo = MagicMock()
        mock_match_repo.get_by_pair.return_value = None

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.cv_generator.match_result_repository", mock_match_repo)

        service = CvGeneratorService()
        with pytest.raises(CvRequiresMatchError, match="Pas de match_result"):
            service.run(1, 1)

    def test_run_success(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        mock_job = MagicMock(
            title="Dev",
            company="Corp",
            location="Paris",
            contract_type="CDI",
            experience="3 ans",
            diploma="Bac +5",
            description="Python SQL",
            skills_extracted=["python", "sql"],
        )
        mock_profile = MagicMock(
            profile_name="test",
            headline="Data Engineer",
            cv_raw_json={"raw_content": "# Jean\n\n## Compétences\n- Python"},
        )

        def get_side_effect(model, id):
            if model == JobOfferModel:
                return mock_job
            if model == CandidateProfileModel:
                return mock_profile
            return None
        mock_session.get.side_effect = get_side_effect

        mock_match = MagicMock(
            id=1,
            total_score=75.0,
            score_breakdown={"title_score": 0.8},
            strengths=["Python"],
            weaknesses=["SQL"],
            missing_skills=["databricks"],
            explanation="Test",
        )

        mock_match_repo = MagicMock()
        mock_match_repo.get_by_pair.return_value = mock_match

        mock_cv_repo = MagicMock()
        mock_cv_repo.upsert.return_value = 42

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.cv_generator.match_result_repository", mock_match_repo)
        monkeypatch.setattr("src.services.cv_generator.cv_version_repository", mock_cv_repo)

        # Mock humanize_cv_markdown
        monkeypatch.setattr(
            "src.services.cv_generator.humanize_cv_markdown",
            lambda job, profile, match: "# [NOM]\n\n## Compétences\n- Python"
        )

        service = CvGeneratorService()
        result = service.run(1, 1)

        assert result["cv_id"] == 42


class TestCvGeneratorServiceDelete:
    """Tests de CvGeneratorService.delete."""

    def test_delete_true(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService

        mock_session = MagicMock()
        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        mock_cv_repo = MagicMock()
        mock_cv_repo.delete_for_pair.return_value = True

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.cv_generator.cv_version_repository", mock_cv_repo)

        service = CvGeneratorService()
        assert service.delete(1, 1) is True

    def test_delete_false(self, monkeypatch):
        from src.services.cv_generator import CvGeneratorService

        mock_session = MagicMock()
        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        mock_cv_repo = MagicMock()
        mock_cv_repo.delete_for_pair.return_value = False

        monkeypatch.setattr("src.services.cv_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.cv_generator.cv_version_repository", mock_cv_repo)

        service = CvGeneratorService()
        assert service.delete(1, 1) is False


# ---------------------------------------------------------------------------
# letter_generator
# ---------------------------------------------------------------------------

class TestLetterGeneratorServiceRun:
    """Tests de LetterGeneratorService.run avec mock de session_scope."""

    def test_run_offre_not_found(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService

        mock_session = MagicMock()
        mock_session.get.return_value = None

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)

        service = LetterGeneratorService()
        with pytest.raises(ValueError, match="Offre.*introuvable"):
            service.run(1, 1)

    def test_run_profil_not_found(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        def get_side_effect(model, id):
            if model == JobOfferModel:
                return MagicMock(title="Dev")
            return None
        mock_session.get.side_effect = get_side_effect

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)

        service = LetterGeneratorService()
        with pytest.raises(ValueError, match="Profil.*introuvable"):
            service.run(1, 1)

    def test_run_no_match(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService, LetterRequiresMatchError
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        def get_side_effect(model, id):
            if model == JobOfferModel:
                return MagicMock(title="Dev")
            if model == CandidateProfileModel:
                return MagicMock(profile_name="test")
            return None
        mock_session.get.side_effect = get_side_effect

        mock_match_repo = MagicMock()
        mock_match_repo.get_by_pair.return_value = None

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.letter_generator.match_result_repository", mock_match_repo)

        service = LetterGeneratorService()
        with pytest.raises(LetterRequiresMatchError, match="Pas de match"):
            service.run(1, 1)

    def test_run_with_existing_cv(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService
        from src.infrastructure.db.models.job_offer import JobOfferModel
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        mock_job = MagicMock(
            title="Dev",
            company="Corp",
            location="Paris",
            contract_type="CDI",
            experience="3 ans",
            diploma="Bac +5",
            description="Python SQL",
            skills_extracted=["python", "sql"],
        )
        mock_profile = MagicMock(
            profile_name="test",
            headline="Data Engineer",
            cv_raw_json={"raw_content": "# Jean\n\n## Compétences\n- Python"},
        )

        def get_side_effect(model, id):
            if model == JobOfferModel:
                return mock_job
            if model == CandidateProfileModel:
                return mock_profile
            return None
        mock_session.get.side_effect = get_side_effect

        mock_match = MagicMock(id=1)

        mock_match_repo = MagicMock()
        mock_match_repo.get_by_pair.return_value = mock_match

        # CV généré existant
        mock_existing_cv = [MagicMock(cv_text="# [NOM]\n\n## Compétences\n- Python")]

        mock_cv_repo = MagicMock()
        mock_cv_repo.list_for_offer.return_value = mock_existing_cv

        mock_letter_repo = MagicMock()
        mock_letter_repo.upsert.return_value = 99

        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.letter_generator.match_result_repository", mock_match_repo)
        monkeypatch.setattr("src.services.letter_generator.cv_version_repository", mock_cv_repo)
        monkeypatch.setattr("src.services.letter_generator.letter_version_repository", mock_letter_repo)

        # Mock humanize_letter_markdown
        monkeypatch.setattr(
            "src.services.letter_generator.humanize_letter_markdown",
            lambda job, profile: "## Objet\nCandidature\n\nMadame, Monsieur,\n\nTest\n\nCordialement,"
        )

        # Mock clean_letter_markdown
        monkeypatch.setattr(
            "src.services.letter_generator.clean_letter_markdown",
            lambda letter, name: letter
        )

        service = LetterGeneratorService()
        result = service.run(1, 1)

        assert result["letter_id"] == 99


class TestLetterGeneratorServiceDelete:
    """Tests de LetterGeneratorService.delete."""

    def test_delete_true(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService

        mock_session = MagicMock()
        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        mock_letter_repo = MagicMock()
        mock_letter_repo.delete_for_pair.return_value = True

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.letter_generator.letter_version_repository", mock_letter_repo)

        service = LetterGeneratorService()
        assert service.delete(1, 1) is True

    def test_delete_false(self, monkeypatch):
        from src.services.letter_generator import LetterGeneratorService

        mock_session = MagicMock()
        mock_session_scope = MagicMock()
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        mock_letter_repo = MagicMock()
        mock_letter_repo.delete_for_pair.return_value = False

        monkeypatch.setattr("src.services.letter_generator.session_scope", mock_session_scope)
        monkeypatch.setattr("src.services.letter_generator.letter_version_repository", mock_letter_repo)

        service = LetterGeneratorService()
        assert service.delete(1, 1) is False
