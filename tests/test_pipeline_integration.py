"""Test d'intégration du pipeline complet : ingestion -> profil -> matching -> CV."""

import json

import pytest
from sqlalchemy import text

from src.infrastructure.db.session import get_engine
from src.services.cv_generator import CvGeneratorService
from src.services.job_analysis import JobAnalysisService
from src.services.job_parser import JobParserService
from src.services.profile_parser import ProfileParserService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_postgres")]

TEST_SOURCE_JOB_ID = "999002"
TEST_PROFILE_NAME = "test_pipeline"


def _db_up() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture()
def _cleanup():
    yield
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM cv_version
                  WHERE job_offer_id IN (SELECT id FROM job_offer WHERE source_job_id = :sid);
                DELETE FROM match_result
                  WHERE job_offer_id IN (SELECT id FROM job_offer WHERE source_job_id = :sid);
                DELETE FROM job_offer WHERE source_job_id = :sid;
                DELETE FROM candidate_profile WHERE profile_name = :pn;
                """
            ),
            {"sid": TEST_SOURCE_JOB_ID, "pn": TEST_PROFILE_NAME},
        )


def test_pipeline_end_to_end(tmp_path, _cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # 1) Offre scrapée -> ingestion
    payload = {
        "id": TEST_SOURCE_JOB_ID,
        "source": "hellowork",
        "url": "https://example.com/job",
        "time_posted": "1 heure",
        "contract_type": "CDI",
        "title": "Data Engineer",
        "company": "Acme",
        "localisation": "Paris",
        "contract_length": "",
        "description": "Python SQL Spark pour la construction de pipelines data",
        "published_date": "01/01/2026",
        "experience": "3 ans",
        "diploma": "Bac+5",
    }
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    (job_dir / f"{TEST_SOURCE_JOB_ID}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    ingested = JobParserService().run(output_dir=job_dir)
    assert ingested["ingested"] == 1

    # 2) Profil candidat (upload d'interface)
    cv = tmp_path / "cv.md"
    cv.write_text(
        "# Test Candidate\n"
        "## Compétences\n"
        "- Python\n"
        "- SQL\n"
        "- Spark\n"
        "## Expérience\n"
        "### Data Engineer — Acme (2020 - 2024)\n"
        "- Pipelines d'ingestion\n",
        encoding="utf-8",
    )
    profile_id = ProfileParserService().run_from_content(
        cv.read_text(encoding="utf-8"),
        profile_name=TEST_PROFILE_NAME,
        filename=cv.name,
    )

    # 3) Matching
    with get_engine().connect() as conn:
        job_id = conn.execute(
            text("SELECT id FROM job_offer WHERE source_job_id = :sid"),
            {"sid": TEST_SOURCE_JOB_ID},
        ).scalar()
    match = JobAnalysisService().run(job_id, profile_id)
    assert 0 <= match["total_score"] <= 100

    # 4) Génération de CV + persistance
    cv_res = CvGeneratorService().run(job_id, profile_id)
    assert cv_res["cv_id"]

    with get_engine().connect() as conn:
        n_match = conn.execute(
            text(
                "SELECT count(*) FROM match_result "
                "WHERE job_offer_id = :jid AND candidate_profile_id = :pid"
            ),
            {"jid": job_id, "pid": profile_id},
        ).scalar()
        n_cv = conn.execute(
            text("SELECT count(*) FROM cv_version WHERE job_offer_id = :jid"),
            {"jid": job_id},
        ).scalar()
    assert n_match == 1
    assert n_cv == 1

    # 5) Re-génération -> remplace le CV du couple : même ligne, toujours une seule
    cv_res2 = CvGeneratorService().run(job_id, profile_id)
    assert cv_res2["cv_id"] == cv_res["cv_id"]
    with get_engine().connect() as conn:
        n_cv2 = conn.execute(
            text("SELECT count(*) FROM cv_version WHERE job_offer_id = :jid"),
            {"jid": job_id},
        ).scalar()
    assert n_cv2 == 1
