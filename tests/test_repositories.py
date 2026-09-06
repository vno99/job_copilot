"""Tests unitaires pour les repositories (mock de la session SQLAlchemy).

Ces tests n'utilisent pas de base de données : ils mockent `session.execute`,
`session.scalars`, `session.get`, etc.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# candidate_profile_repository
# ---------------------------------------------------------------------------

class TestCandidateProfileRepository:
    """Tests de candidate_profile_repository."""

    def test_get_by_name_found(self):
        from src.infrastructure.db.repositories import candidate_profile_repository
        from src.infrastructure.db.models.candidate_profile import CandidateProfileModel

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(profile_name="test")

        result = candidate_profile_repository.get_by_name(mock_session, "test")

        assert result.profile_name == "test"
        mock_session.scalars.assert_called_once()

    def test_get_by_name_not_found(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = None

        result = candidate_profile_repository.get_by_name(mock_session, "nonexistent")

        assert result is None

    def test_upsert(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one.return_value = 42

        profile = {"profile_name": "test", "skills": ["python"]}
        result = candidate_profile_repository.upsert(mock_session, profile)

        assert result == 42
        mock_session.execute.assert_called_once()

    def test_insert(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 99
        mock_session.add = MagicMock()
        mock_session.flush = MagicMock()

        # Patch the model constructor
        with patch(
            "src.infrastructure.db.repositories.candidate_profile_repository.CandidateProfileModel",
            return_value=mock_row
        ):
            result = candidate_profile_repository.insert(mock_session, {"profile_name": "test"})

        assert result == 99

    def test_list_all(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(profile_name="p1"), MagicMock(profile_name="p2")]
        mock_session.scalars.return_value = iter(mock_items).__iter__()

        # list_all fait list(session.scalars(stmt))
        mock_session.scalars.return_value = mock_items

        result = candidate_profile_repository.list_all(mock_session)

        assert len(result) == 2

    def test_get_active_found(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(profile_name="active")

        result = candidate_profile_repository.get_active(mock_session)

        assert result.profile_name == "active"

    def test_get_active_not_found(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = None

        result = candidate_profile_repository.get_active(mock_session)

        assert result is None

    def test_set_active_true_existing(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_target = MagicMock()
        mock_session.get.return_value = mock_target

        result = candidate_profile_repository.set_active(mock_session, 1, True)

        assert result is True
        mock_session.execute.assert_called_once()  # Désactiver les autres
        assert mock_target.is_active is True

    def test_set_active_false_existing(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_target = MagicMock()
        mock_session.get.return_value = mock_target

        result = candidate_profile_repository.set_active(mock_session, 1, False)

        assert result is True
        mock_session.execute.assert_not_called()  # Pas de désactivation des autres
        assert mock_target.is_active is False

    def test_set_active_not_existing(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = candidate_profile_repository.set_active(mock_session, 999, True)

        assert result is False

    def test_rename_existing(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_row = MagicMock(profile_name="old")
        mock_session.get.return_value = mock_row

        result = candidate_profile_repository.rename(mock_session, 1, "new_name")

        assert result.profile_name == "new_name"
        assert mock_row.profile_name == "new_name"

    def test_rename_not_existing(self):
        from src.infrastructure.db.repositories import candidate_profile_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = candidate_profile_repository.rename(mock_session, 999, "new_name")

        assert result is None


# ---------------------------------------------------------------------------
# cv_version_repository
# ---------------------------------------------------------------------------

class TestCvVersionRepository:
    """Tests de cv_version_repository."""

    def test_get_by_id_found(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(id=1)

        result = cv_version_repository.get_by_id(mock_session, 1)

        assert result.id == 1

    def test_get_by_id_not_found(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = cv_version_repository.get_by_id(mock_session, 999)

        assert result is None

    def test_set_application_submitted_found(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_session.get.return_value = mock_row

        result = cv_version_repository.set_application_submitted(mock_session, 1, True)

        assert result == mock_row
        assert mock_row.application_submitted is True
        mock_session.flush.assert_called_once()

    def test_set_application_submitted_not_found(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = cv_version_repository.set_application_submitted(mock_session, 999, True)

        assert result is None

    def test_list_for_offer(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(id=1), MagicMock(id=2)]
        mock_session.scalars.return_value = mock_items

        result = cv_version_repository.list_for_offer(mock_session, 1, 1)

        assert len(result) == 2

    def test_upsert(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one.return_value = 42

        record = {
            "job_offer_id": 1,
            "candidate_profile_id": 1,
            "cv_text": "# CV",
        }
        result = cv_version_repository.upsert(mock_session, record)

        assert result == 42
        mock_session.execute.assert_called_once()

    def test_delete_for_pair_true(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        result = cv_version_repository.delete_for_pair(mock_session, 1, 1)

        assert result is True

    def test_delete_for_pair_false(self):
        from src.infrastructure.db.repositories import cv_version_repository

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        result = cv_version_repository.delete_for_pair(mock_session, 1, 1)

        assert result is False


# ---------------------------------------------------------------------------
# letter_version_repository
# ---------------------------------------------------------------------------

class TestLetterVersionRepository:
    """Tests de letter_version_repository."""

    def test_get_by_id_found(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(id=1)

        result = letter_version_repository.get_by_id(mock_session, 1)

        assert result.id == 1

    def test_get_by_id_not_found(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = letter_version_repository.get_by_id(mock_session, 999)

        assert result is None

    def test_list_for_offer(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(id=1)]
        mock_session.scalars.return_value = mock_items

        result = letter_version_repository.list_for_offer(mock_session, 1, 1)

        assert len(result) == 1

    def test_upsert(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one.return_value = 99

        record = {
            "job_offer_id": 1,
            "candidate_profile_id": 1,
            "letter_text": "Madame, Monsieur",
        }
        result = letter_version_repository.upsert(mock_session, record)

        assert result == 99

    def test_delete_for_pair_true(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        result = letter_version_repository.delete_for_pair(mock_session, 1, 1)

        assert result is True

    def test_delete_for_pair_false(self):
        from src.infrastructure.db.repositories import letter_version_repository

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        result = letter_version_repository.delete_for_pair(mock_session, 1, 1)

        assert result is False


# ---------------------------------------------------------------------------
# match_result_repository
# ---------------------------------------------------------------------------

class TestMatchResultRepository:
    """Tests de match_result_repository."""

    def test_exists_true(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.first.return_value = (1,)

        result = match_result_repository.exists(mock_session, 1, 1)

        assert result is True

    def test_exists_false(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.first.return_value = None

        result = match_result_repository.exists(mock_session, 1, 1)

        assert result is False

    def test_get_by_pair_found(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(id=1)

        result = match_result_repository.get_by_pair(mock_session, 1, 1)

        assert result.id == 1

    def test_get_by_pair_not_found(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = None

        result = match_result_repository.get_by_pair(mock_session, 1, 1)

        assert result is None

    def test_delete_for_pair_true(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        # exists() appelle session.execute(stmt).first() → doit retourner (1,)
        mock_session.execute.return_value.first.return_value = (1,)
        # Les DELETE renvoient des rowcount
        mock_session.execute.return_value.rowcount = 1

        result = match_result_repository.delete_for_pair(mock_session, 1, 1)

        assert result is True

    def test_delete_for_pair_false(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.first.return_value = None

        result = match_result_repository.delete_for_pair(mock_session, 1, 1)

        assert result is False

    def test_upsert(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one.return_value = 42

        record = {
            "job_offer_id": 1,
            "candidate_profile_id": 1,
            "total_score": 75.0,
        }
        result = match_result_repository.upsert(mock_session, record)

        assert result == 42

    def test_list_unmatched_cv(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(id=1), MagicMock(id=2)]
        mock_session.scalars.return_value = mock_items

        result = match_result_repository.list_unmatched_cv(mock_session, 1)

        assert len(result) == 2

    def test_list_unmatched_cv_with_limit(self):
        from src.infrastructure.db.repositories import match_result_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(id=1)]
        mock_session.scalars.return_value = mock_items

        result = match_result_repository.list_unmatched_cv(mock_session, 1, limit=5)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# search_parameters_repository
# ---------------------------------------------------------------------------

class TestSearchParametersRepository:
    """Tests de search_parameters_repository."""

    def test_list_all(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_items = [MagicMock(id=1), MagicMock(id=2)]
        mock_session.scalars.return_value = mock_items

        result = search_parameters_repository.list_all(mock_session)

        assert len(result) == 2

    def test_get_by_url_found(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(url="https://example.com")

        result = search_parameters_repository.get_by_url(mock_session, "https://example.com")

        assert result.url == "https://example.com"

    def test_get_by_url_not_found(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = None

        result = search_parameters_repository.get_by_url(mock_session, "https://notfound.com")

        assert result is None

    def test_get_by_id_found(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(id=1)

        result = search_parameters_repository.get_by_id(mock_session, 1)

        assert result.id == 1

    def test_get_by_id_not_found(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = search_parameters_repository.get_by_id(mock_session, 999)

        assert result is None

    def test_insert(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 42
        mock_session.add = MagicMock()
        mock_session.flush = MagicMock()

        with patch(
            "src.infrastructure.db.repositories.search_parameters_repository.SearchParameterModel",
            return_value=mock_row
        ):
            result = search_parameters_repository.insert(mock_session, {"title": "test"})

        assert result == 42

    def test_update_existing(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_row = MagicMock(title="old")
        mock_session.get.return_value = mock_row

        data = {
            "title": "new_title",
            "source": "new_source",
            "url": "https://new.com",
            "max_offers": 10,
        }
        result = search_parameters_repository.update(mock_session, 1, data)

        assert result == mock_row
        assert mock_row.title == "new_title"
        assert mock_row.source == "new_source"
        assert mock_row.url == "https://new.com"
        assert mock_row.max_offers == 10

    def test_update_not_existing(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = search_parameters_repository.update(mock_session, 999, {})

        assert result is None

    def test_set_active_true(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_session.get.return_value = mock_row

        result = search_parameters_repository.set_active(mock_session, 1, True)

        assert result is True
        assert mock_row.is_active is True

    def test_set_active_false(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_session.get.return_value = mock_row

        result = search_parameters_repository.set_active(mock_session, 1, False)

        assert result is True
        assert mock_row.is_active is False

    def test_set_active_not_found(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = search_parameters_repository.set_active(mock_session, 999, True)

        assert result is False

    def test_delete_existing(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_session.get.return_value = mock_row

        result = search_parameters_repository.delete(mock_session, 1)

        assert result is True
        mock_session.delete.assert_called_once_with(mock_row)

    def test_delete_not_existing(self):
        from src.infrastructure.db.repositories import search_parameters_repository

        mock_session = MagicMock()
        mock_session.get.return_value = None

        result = search_parameters_repository.delete(mock_session, 999)

        assert result is False


# ---------------------------------------------------------------------------
# job_offer_repository
# ---------------------------------------------------------------------------

class TestJobOfferRepository:
    """Tests de job_offer_repository."""

    def test_fetch_existing_empty_rows(self):
        from src.infrastructure.db.repositories.job_offer_repository import _fetch_existing

        result = _fetch_existing(MagicMock(), [])
        assert result == {}

    def test_fetch_existing_with_rows(self):
        from src.infrastructure.db.repositories.job_offer_repository import _fetch_existing
        from src.infrastructure.db.models.job_offer import JobOfferModel

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.source = "hellowork"
        mock_row.source_job_id = "123"
        mock_row.id = 1
        mock_row.content_hash = "abc"

        mock_execute = MagicMock(return_value=[mock_row])
        mock_session.execute = mock_execute

        rows = [{"source": "hellowork", "source_job_id": "123"}]
        result = _fetch_existing(mock_session, rows)

        assert result[("hellowork", "123")] == (1, "abc")

    def test_upsert_many_all_insert(self):
        from src.infrastructure.db.repositories.job_offer_repository import upsert_many, _fetch_existing

        mock_session = MagicMock()
        # _fetch_existing returns empty
        mock_session.execute.return_value = MagicMock(rowcount=2)

        rows = [
            {
                "source": "hellowork",
                "source_job_id": "123",
                "title": "Dev",
                "company": "Corp",
                "content_hash": "hash1",
            },
            {
                "source": "hellowork",
                "source_job_id": "456",
                "title": "Data",
                "company": "Acme",
                "content_hash": "hash2",
            },
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._fetch_existing",
            return_value={}
        ):
            ingested, updated, unchanged = upsert_many(mock_session, rows)

        assert ingested == 2
        assert updated == 0
        assert unchanged == 0

    def test_upsert_many_all_unchanged(self):
        from src.infrastructure.db.repositories.job_offer_repository import upsert_many

        mock_session = MagicMock()

        rows = [
            {
                "source": "hellowork",
                "source_job_id": "123",
                "title": "Dev",
                "content_hash": "same_hash",
            },
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._fetch_existing",
            return_value={("hellowork", "123"): (1, "same_hash")}
        ):
            ingested, updated, unchanged = upsert_many(mock_session, rows)

        assert ingested == 0
        assert updated == 0
        assert unchanged == 1

    def test_upsert_many_update(self):
        from src.infrastructure.db.repositories.job_offer_repository import upsert_many

        mock_session = MagicMock()

        rows = [
            {
                "source": "hellowork",
                "source_job_id": "123",
                "title": "Dev Updated",
                "content_hash": "new_hash",
            },
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._fetch_existing",
            return_value={("hellowork", "123"): (1, "old_hash")}
        ):
            ingested, updated, unchanged = upsert_many(mock_session, rows)

        assert ingested == 0
        assert updated == 1
        assert unchanged == 0

    def test_get_by_url(self):
        from src.infrastructure.db.repositories.job_offer_repository import get_by_url

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(id=1)

        result = get_by_url(mock_session, "https://example.com/job/1")

        assert result.id == 1

    def test_get_by_url_not_found(self):
        from src.infrastructure.db.repositories.job_offer_repository import get_by_url

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = None

        result = get_by_url(mock_session, "https://notfound.com")

        assert result is None

    def test_get_by_url_for_update(self):
        from src.infrastructure.db.repositories.job_offer_repository import get_by_url_for_update

        mock_session = MagicMock()
        mock_session.scalars.return_value.first.return_value = MagicMock(id=1)

        result = get_by_url_for_update(mock_session, "https://example.com/job/1")

        assert result.id == 1

    def test_existing_urls_empty(self):
        from src.infrastructure.db.repositories.job_offer_repository import existing_urls

        mock_session = MagicMock()
        mock_session.execute.return_value = iter([]).__iter__()

        result = existing_urls(mock_session, [])

        assert result == set()

    def test_existing_urls_with_data(self):
        from src.infrastructure.db.repositories.job_offer_repository import existing_urls

        mock_session = MagicMock()
        mock_session.execute.return_value = [("https://example.com/1",), ("https://example.com/2",)]

        result = existing_urls(mock_session, ["https://example.com/1", "https://example.com/2", "https://new.com"])

        assert result == {"https://example.com/1", "https://example.com/2"}

    def test_get_by_keys_empty(self):
        from src.infrastructure.db.repositories.job_offer_repository import get_by_keys

        mock_session = MagicMock()

        result = get_by_keys(mock_session, [])

        assert result == []

    def test_get_by_keys(self):
        from src.infrastructure.db.repositories.job_offer_repository import get_by_keys

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.source = "hellowork"
        mock_row.source_job_id = "123"
        mock_session.execute.return_value.scalars.return_value = [mock_row]

        result = get_by_keys(mock_session, [("hellowork", "123")])

        assert len(result) == 1

    def test_recent_urls(self):
        from src.infrastructure.db.repositories.job_offer_repository import recent_urls

        mock_session = MagicMock()
        mock_session.execute.return_value = [
            ("https://example.com/1",),
            ("https://example.com/2",),
        ]

        result = recent_urls(mock_session, limit=10)

        assert result == ["https://example.com/1", "https://example.com/2"]

    def test_set_archived(self):
        from src.infrastructure.db.repositories.job_offer_repository import set_archived

        mock_session = MagicMock()

        set_archived(mock_session, 1, True)

        mock_session.execute.assert_called_once()

    def test_scores_for_offer(self):
        from src.infrastructure.db.repositories.job_offer_repository import scores_for_offer
        from src.infrastructure.db.models.match_result import MatchResultModel

        mock_session = MagicMock()
        mock_match = MagicMock(spec=MatchResultModel)
        mock_match.job_offer_id = 1
        mock_match.total_score = 75.0

        # Simuler le résultat de _scores_for_offers
        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={1: [(mock_match, "test_profile", True, True, False)]}
        ):
            result = scores_for_offer(mock_session, 1)

        assert len(result) == 1
        assert result[0][0] == mock_match

    def test_list_offers_invalid_sort_column(self):
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()

        with pytest.raises(ValueError, match="tri inconnu"):
            list_offers(mock_session, sort_by="invalid_column")

    def test_list_offers_invalid_order(self):
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()

        with pytest.raises(ValueError, match="ordre de tri inconnu"):
            list_offers(mock_session, order="invalid")

    def test_neighbors_not_found(self):
        from src.infrastructure.db.repositories.job_offer_repository import neighbors

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        prev, next_id = neighbors(mock_session, 999, archived=False)

        assert prev is None
        assert next_id is None


# ---------------------------------------------------------------------------
# stats_repository
# ---------------------------------------------------------------------------

class TestStatsRepository:
    """Tests de stats_repository."""

    def test_get_stats(self):
        from src.infrastructure.db.repositories import stats_repository

        mock_session = MagicMock()

        def execute_side_effect(stmt):
            # Retourne des valeurs différentes selon la requête
            stmt_str = str(stmt)
            if "count" in stmt_str and "distinct" in stmt_str:
                return MagicMock(scalar_one=MagicMock(return_value=10))
            if "max" in stmt_str:
                return MagicMock(scalar_one=MagicMock(return_value="2024-01-01"))
            if "count" in stmt_str:
                return MagicMock(scalar_one=MagicMock(return_value=100))
            return MagicMock(scalar_one=MagicMock(return_value=50))

        mock_session.execute.side_effect = execute_side_effect

        result = stats_repository.get_stats(mock_session)

        assert "offers_total" in result
        assert "offers_with_cv" in result
        assert "cvs_generated" in result
        assert "last_ingested_at" in result


class TestJobOfferRepositoryExtra:
    """Tests supplementaires pour job_offer_repository."""

    def test_scores_for_offers_with_multiple_matches(self):
        """_scores_for_offers groupe plusieurs matchs par offre."""
        from src.infrastructure.db.repositories.job_offer_repository import _scores_for_offers

        mock_session = MagicMock()
        # Simule plusieurs rows de match pour la meme offre (profils differents)
        mock_row1 = MagicMock()
        mock_row1.job_offer_id = 1
        mock_row1.total_score = 80.0
        mock_row1.profile_name = "Profil A"
        mock_row1.cv_id = 10
        mock_row1.application_submitted = True
        mock_row1.letter_id = 20

        mock_row2 = MagicMock()
        mock_row2.job_offer_id = 1
        mock_row2.total_score = 65.0
        mock_row2.profile_name = "Profil B"
        mock_row2.cv_id = None
        mock_row2.application_submitted = False
        mock_row2.letter_id = None

        mock_session.execute.return_value = [
            (mock_row1, "Profil A", 10, True, 20),
            (mock_row2, "Profil B", None, False, None),
        ]

        result = _scores_for_offers(mock_session, [1])

        assert 1 in result
        matches = result[1]
        assert len(matches) == 2
        # Tri par score DESC -> premier est 80.0
        assert matches[0][0].total_score == 80.0
        assert matches[0][1] == "Profil A"
        assert matches[0][2] is True   # has_cv
        assert matches[0][3] is True   # has_letter
        assert matches[0][4] is True   # application_submitted
        assert matches[1][1] == "Profil B"
        assert matches[1][2] is False  # pas de CV
        assert matches[1][3] is False  # pas de lettre

    def test_scores_for_offers_empty_ids(self):
        """_scores_for_offers renvoie {} si la liste d'ids est vide."""
        from src.infrastructure.db.repositories.job_offer_repository import _scores_for_offers
        mock_session = MagicMock()
        result = _scores_for_offers(mock_session, [])
        assert result == {}


    def test_list_offers_with_company_filter(self):
        """list_offers filtre par nom d'entreprise (insensible a la casse)."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Dev"
        mock_row.company = "Acme"
        mock_row.location = "Paris"
        mock_row.source = "hellowork"
        mock_row.ingested_at = None
        mock_row.archived = False

        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=1)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=1)),  # count
            MagicMock(all=MagicMock(return_value=[(mock_row,)]), scalars=MagicMock(return_value=[(mock_row,)])),  # rows
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, company="acme")

        assert total == 1

    def test_list_offers_with_source_filter(self):
        """list_offers filtre par source."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=0)),  # count
            MagicMock(all=MagicMock(return_value=[]), scalars=MagicMock(return_value=[])),  # rows
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, source="hellowork")

        assert total == 0

    def test_list_offers_with_archived_filter(self):
        """list_offers filtre par archived."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=0)),
            MagicMock(all=MagicMock(return_value=[]), scalars=MagicMock(return_value=[])),
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, archived=True)

        assert total == 0

    def test_neighbors_prev_and_next(self):
        """neighbors renvoie les ids precedent et suivant existants."""
        from src.infrastructure.db.repositories.job_offer_repository import neighbors

        mock_session = MagicMock()
        # Setup: current job ingested_at = 2024-01-01, id=5
        mock_session.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value="2024-01-01")),  # current
            MagicMock(scalar_one_or_none=MagicMock(return_value=3)),  # previous
            MagicMock(scalar_one_or_none=MagicMock(return_value=7)),  # next
        ]

        prev, next_id = neighbors(mock_session, 5, archived=False)

        assert prev == 3
        assert next_id == 7

    def test_neighbors_at_boundary(self):
        """neighbors renvoie None pour les extremites."""
        from src.infrastructure.db.repositories.job_offer_repository import neighbors

        mock_session = MagicMock()
        mock_session.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value="2024-01-01")),  # current
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no previous
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no next
        ]

        prev, next_id = neighbors(mock_session, 5, archived=False)

        assert prev is None
        assert next_id is None


class TestJobOfferRepositoryExtra:
    """Tests supplementaires pour job_offer_repository."""

    def test_scores_for_offers_with_multiple_matches(self):
        """_scores_for_offers groupe plusieurs matchs par offre."""
        from src.infrastructure.db.repositories.job_offer_repository import _scores_for_offers

        mock_session = MagicMock()
        # Simule plusieurs rows de match pour la meme offre (profils differents)
        mock_row1 = MagicMock()
        mock_row1.job_offer_id = 1
        mock_row1.total_score = 80.0
        mock_row1.profile_name = "Profil A"
        mock_row1.cv_id = 10
        mock_row1.application_submitted = True
        mock_row1.letter_id = 20

        mock_row2 = MagicMock()
        mock_row2.job_offer_id = 1
        mock_row2.total_score = 65.0
        mock_row2.profile_name = "Profil B"
        mock_row2.cv_id = None
        mock_row2.application_submitted = False
        mock_row2.letter_id = None

        mock_session.execute.return_value = [
            (mock_row1, "Profil A", 10, True, 20),
            (mock_row2, "Profil B", None, False, None),
        ]

        result = _scores_for_offers(mock_session, [1])

        assert 1 in result
        matches = result[1]
        assert len(matches) == 2
        # Tri par score DESC -> premier est 80.0
        assert matches[0][0].total_score == 80.0
        assert matches[0][1] == "Profil A"
        assert matches[0][2] is True   # has_cv
        assert matches[0][3] is True   # has_letter
        assert matches[0][4] is True   # application_submitted
        assert matches[1][1] == "Profil B"
        assert matches[1][2] is False  # pas de CV
        assert matches[1][3] is False  # pas de lettre

    def test_scores_for_offers_empty_ids(self):
        """_scores_for_offers renvoie {} si la liste d'ids est vide."""
        from src.infrastructure.db.repositories.job_offer_repository import _scores_for_offers
        mock_session = MagicMock()
        result = _scores_for_offers(mock_session, [])
        assert result == {}


    def test_list_offers_with_company_filter(self):
        """list_offers filtre par nom d'entreprise (insensible a la casse)."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Dev"
        mock_row.company = "Acme"
        mock_row.location = "Paris"
        mock_row.source = "hellowork"
        mock_row.ingested_at = None
        mock_row.archived = False

        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=1)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=1)),  # count
            MagicMock(all=MagicMock(return_value=[(mock_row,)]), scalars=MagicMock(return_value=[(mock_row,)])),  # rows
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, company="acme")

        assert total == 1

    def test_list_offers_with_source_filter(self):
        """list_offers filtre par source."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=0)),  # count
            MagicMock(all=MagicMock(return_value=[]), scalars=MagicMock(return_value=[])),  # rows
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, source="hellowork")

        assert total == 0

    def test_list_offers_with_archived_filter(self):
        """list_offers filtre par archived."""
        from src.infrastructure.db.repositories.job_offer_repository import list_offers

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0)
        )
        mock_session.execute.side_effect = [
            MagicMock(scalar_one=MagicMock(return_value=0)),
            MagicMock(all=MagicMock(return_value=[]), scalars=MagicMock(return_value=[])),
        ]

        with patch(
            "src.infrastructure.db.repositories.job_offer_repository._scores_for_offers",
            return_value={}
        ):
            total, rows = list_offers(mock_session, archived=True)

        assert total == 0

    def test_neighbors_prev_and_next(self):
        """neighbors renvoie les ids precedent et suivant existants."""
        from src.infrastructure.db.repositories.job_offer_repository import neighbors

        mock_session = MagicMock()
        # Setup: current job ingested_at = 2024-01-01, id=5
        mock_session.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value="2024-01-01")),  # current
            MagicMock(scalar_one_or_none=MagicMock(return_value=3)),  # previous
            MagicMock(scalar_one_or_none=MagicMock(return_value=7)),  # next
        ]

        prev, next_id = neighbors(mock_session, 5, archived=False)

        assert prev == 3
        assert next_id == 7

    def test_neighbors_at_boundary(self):
        """neighbors renvoie None pour les extremites."""
        from src.infrastructure.db.repositories.job_offer_repository import neighbors

        mock_session = MagicMock()
        mock_session.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value="2024-01-01")),  # current
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no previous
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no next
        ]

        prev, next_id = neighbors(mock_session, 5, archived=False)

        assert prev is None
        assert next_id is None

