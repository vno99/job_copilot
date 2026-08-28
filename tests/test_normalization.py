from datetime import date

from src.core.domain.job_offer import JobOffer
from src.services.job_parser import (
    _diploma_to_text,
    _parse_published_date,
    normalize_job_offer,
)


def _sample_job_offer() -> JobOffer:
    return JobOffer(
        id="79299371",
        source="hellowork",
        url="https://www.hellowork.com/fr-fr/emplois/79299371.html",
        time_posted="2 heures",
        contract_type="CDI",
        title="Data Engineer H/F",
        company="Alfi",
        localisation="Boulogne-Billancourt - 92",
        contract_length="",
        description="Python SQL Databricks",
        published_date="22/05/2026",
        experience="1 an min.",
        diploma="Bac +5",
    )


def test_normalize_mapping():
    row = normalize_job_offer(_sample_job_offer())
    assert row["source"] == "hellowork"
    assert row["source_job_id"] == "79299371"
    assert row["url"] == "https://www.hellowork.com/fr-fr/emplois/79299371.html"
    assert row["location"] == "Boulogne-Billancourt - 92"
    assert row["contract_type"] == "CDI"
    assert row["published_date"] == date(2026, 5, 22)
    assert row["diploma"] == "Bac +5"
    assert row["description"] == "Python SQL Databricks"
    assert row["content_hash"]
    assert row["skills_extracted"]  # extraction non vide


def test_normalize_content_hash_stable():
    a = normalize_job_offer(_sample_job_offer())
    b = normalize_job_offer(_sample_job_offer())
    assert a["content_hash"] == b["content_hash"]


def test_parse_published_date():
    assert _parse_published_date("22/05/2026") == date(2026, 5, 22)
    assert _parse_published_date("2026-05-22") == date(2026, 5, 22)
    assert _parse_published_date(None) is None
    assert _parse_published_date("") is None


def test_diploma_to_text():
    assert _diploma_to_text(["Bac +5", "Master"]) == "Bac +5, Master"
    assert _diploma_to_text("Bac +5") == "Bac +5"
    assert _diploma_to_text(None) is None
