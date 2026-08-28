import json

import pytest
from sqlalchemy import text

from src.infrastructure.db.session import get_engine
from src.services.job_parser import JobParserService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_postgres")]

TEST_SOURCE_JOB_ID = "999001"


def _db_up() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture()
def tmp_job_dir(tmp_path):
    payload = {
        "id": TEST_SOURCE_JOB_ID,
        "source": "hellowork",
        "url": "https://www.hellowork.com/fr-fr/emplois/999001.html",
        "time_posted": "1 heure",
        "contract_type": "CDI",
        "title": "Data Engineer",
        "company": "Acme",
        "localisation": "Paris",
        "contract_length": "",
        "description": "Python SQL Databricks",
        "published_date": "22/05/2026",
        "experience": "3 ans",
        "diploma": "Bac+5",
    }
    (tmp_path / f"{TEST_SOURCE_JOB_ID}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def _cleanup():
    yield
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM job_offer WHERE source_job_id = :sid"),
            {"sid": TEST_SOURCE_JOB_ID},
        )


def test_ingest_is_idempotent(tmp_job_dir, _cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    service = JobParserService()
    first = service.run(output_dir=tmp_job_dir)
    second = service.run(output_dir=tmp_job_dir)

    assert first["ingested"] == 1
    assert second["ingested"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 1
