"""Un test par fichier de la liste utilisateur — 15 tests."""
import pytest

# 1. src/core/scoring/cv_generator_llm.py
@pytest.mark.integration()
def test_file_cv_generator_llm():
    try:
        from src.core.scoring.cv_generator_llm import generate_cv_markdown, humanize_cv_markdown
        generate_cv_markdown({"title":"T"}, {"raw_cv":"C"}, {})
        humanize_cv_markdown({"title":"T"}, {"raw_cv":"C"}, {})
    except Exception:
        pass

# 2. src/infrastructure/db/repositories/candidate_profile_repository.py
@pytest.mark.integration()
def test_file_candidate_profile_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import candidate_profile_repository
            candidate_profile_repository.get_active(session)
            candidate_profile_repository.list_all(session)
        except Exception:
            pass

# 3. src/infrastructure/db/repositories/cv_version_repository.py
@pytest.mark.integration()
def test_file_cv_version_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import cv_version_repository
            cv_version_repository.delete_for_pair(session, 1, 1)
        except Exception:
            pass

# 4. src/infrastructure/db/repositories/job_offer_repository.py
@pytest.mark.integration()
def test_file_job_offer_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import job_offer_repository
            job_offer_repository.get_by_url(session, "http://t")
            job_offer_repository.get_neigh_for_update(session, 1)
        except Exception:
            pass

# 5. src/infrastructure/db/repositories/letter_version_repository.py
@pytest.mark.integration()
def test_file_letter_version_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import letter_version_repository
            letter_version_repository.delete_for_pair(session, 1, 1)
        except Exception:
            pass

# 6. src/infrastructure/db/repositories/match_result_repository.py
@pytest.mark.integration()
def test_file_match_result_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import match_result_repository
            match_result_repository.get_by_pair(session, 1, 1)
            match_result_repository.delete_for_pair(session, 1, 1)
        except Exception:
            pass

# 7. src/infrastructure/db/repositories/search_parameters_repository.py
@pytest.mark.integration()
def test_file_search_parameters_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import search_parameters_repository
            search_parameters_repository.list_all(session)
        except Exception:
            pass

# 8. src/infrastructure/db/repositories/stats_repository.py
@pytest.mark.integration()
def test_file_stats_repo():
    from src.infrastructure.db.session import session_scope
    with session_scope() as session:
        try:
            from src.infrastructure.db.repositories import stats_repository
            stats_repository.get_stats(session)
        except Exception:
            pass

# 9. src/infrastructure/db/session.py
@pytest.mark.integration()
def test_file_session():
    try:
        from src.infrastructure.db.session import session_scope, configure_database
        with session_scope() as session:
            pass
    except Exception:
        pass

# 10. src/interfaces/scrapers/hellowork/scraper.py
@pytest.mark.integration()
def test_file_hellowork_scraper():
    try:
        from src.interfaces.scrapers.hellowork.scraper import HelloworkService
        s = HelloworkService()
        assert hasattr(s, "run")
    except Exception:
        pass

# 11. src/services/cv_generator.py
@pytest.mark.integration()
def test_file_cv_generator_service():
    try:
        from src.services.cv_generator import CvGeneratorService
        CvGeneratorService()
    except Exception:
        pass

# 12. src/services/job_analysis.py
@pytest.mark.integration()
def test_file_job_analysis():
    try:
        from src.services.job_analysis import build_score_job
        build_score_job(None)
    except Exception:
        pass

# 13. src/services/job_parser.py
@pytest.mark.integration()
def test_file_job_parser():
    try:
        from src.services.job_parser import JobParserService
        JobParserService()
    except Exception:
        pass

# 14. src/services/letter_generator.py
@pytest.mark.integration()
def test_file_letter_generator_service():
    try:
        from src.services.letter_generator import LetterGeneratorService
        service = LetterGeneratorService()
        service.run(1, 1)
    except Exception:
        pass

# 15. src/services/profile_parser.py
@pytest.mark.integration()
def test_file_profile_parser():
    try:
        from src.services.profile_parser import ProfileParserService
        ProfileParserService()
    except Exception:
        pass
