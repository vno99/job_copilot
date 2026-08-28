from pathlib import Path

from src.services.profile_parser import (
    _parse_experience_blocks,
    cv_source_to_markdown,
    parse_cv,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_parse_cv_sample():
    markdown = (FIXTURES_DIR / "sample_cv.md").read_text(encoding="utf-8")
    parsed = parse_cv(markdown)

    assert parsed["headline"] == "Jean Dupont"
    assert "Data Engineer" in parsed["summary"]
    assert "Python" in parsed["skills"]
    assert "SQL" in parsed["skills"]

    experiences = parsed["experiences"]
    assert any("Acme Corp" in e["title"] for e in experiences)
    assert any("Startup XYZ" in e["title"] for e in experiences)

    # La première expérience contient des puces
    acme = next(e for e in experiences if "Acme Corp" in e["title"])
    assert len(acme["bullets"]) >= 1
    assert any("Airflow" in b for b in acme["bullets"])

    # Formation : chaque diplôme est une entrée
    assert any("Master" in d for d in parsed["education"])


_BOLD_CV = """**NOUANE Victor**

**Data Engineer | Software Engineering & Data Pipelines**
77360 VAIRES SUR MARNE | nouane_v@hotmail.com

**Résumé professionnel**

Ingénieur expérimenté spécialisé dans la conception de pipelines de données.

**Compétences clés**

-    **Data Engineering** : Python, SQL, PostgreSQL, Airflow, dbt, ETL
-    **AI & LLM** : RAG, Embeddings, Vector Databases

**Projets Data**

**Pipeline ELT & Modélisation Data —** [github.com/vno99/pmu](https://github.com/vno99/pmu)

-    Ingestion automatisée de 250 000 fichiers JSON
-    Orchestration d'un pipeline Airflow sous Docker

**Expérience professionnelle**

**Tech Lead Java / Data Processing — BNP Paribas CIB — Montreuil (93)**

**01/2022 — 06/2025**

-    Pilotage de migrations de données critiques
-    Développement de traitements batch avec Spring Batch et SQL

**Stack** : Java 17, Spring Boot, Kubernetes, Git, CI/CD

**Développeur Java Senior — Infogreffe — Télétravail**

**07/2021 - 01/2022**

-    Développement et maintenance de services

**Formation**

**Architecte en intelligence artificielle** — RNCP 7
**DUT Informatique** — IUT de Villetaneuse
"""


def test_parse_cv_bold_sections():
    """CV dont les titres sont en **gras** (éditeurs sans headings ``#``)."""
    parsed = parse_cv(_BOLD_CV)

    assert parsed["headline"] == "NOUANE Victor"
    assert "pipelines de données" in parsed["summary"]

    # Les compétences sont extraites ; les catégories en gras sont retirées.
    skills = parsed["skills"]
    assert "Python" in skills
    assert "SQL" in skills
    assert "Airflow" in skills
    assert not any("Data Engineering" in s for s in skills)
    # Le contenu de la section « Projets » ne pollue pas les compétences.
    assert not any("github.com" in s or "Ingestion" in s for s in skills)

    experiences = parsed["experiences"]
    assert len(experiences) == 2
    tech_lead = experiences[0]
    assert "BNP Paribas CIB" in tech_lead["title"]
    # La période en gras est rattachée au titre du poste.
    assert "01/2022" in tech_lead["title"]
    assert any("Pilotage" in b for b in tech_lead["bullets"])
    # La ligne « Stack : … » est conservée comme puce.
    assert any("Java 17" in b for b in tech_lead["bullets"])

    assert parsed["education"]
    assert any("DUT" in d for d in parsed["education"])


def test_parse_experience_blocks_period_attached_when_no_bullets():
    """La période en gras est rattachée au titre du poste en cours, même sans
    puces entre le titre et la période (format usuel des CV en gras)."""
    blocks = _parse_experience_blocks(
        [
            "**Data Engineer — Acme**",
            "**01/2022 — 06/2025**",
            "- Pipeline Airflow",
        ]
    )
    assert len(blocks) == 1
    assert blocks[0]["title"] == "Data Engineer — Acme — 01/2022 — 06/2025"
    assert blocks[0]["bullets"] == ["Pipeline Airflow"]


def test_parse_experience_blocks_two_jobs_without_bullets():
    """Deux postes consécutifs en gras sans puces entre eux ne doivent pas
    fusionner : ``**Poste 1**`` puis ``**Poste 2**`` = deux expériences, pas
    « Poste 1 — Poste 2 ». Seule une ligne qui ressemble à une date est une
    période ; un titre ne l'est pas."""
    blocks = _parse_experience_blocks(
        [
            "**Data Engineer — Acme**",
            "**Data Analyst — Beta**",
            "- Dashboards",
        ]
    )
    assert [b["title"] for b in blocks] == [
        "Data Engineer — Acme",
        "Data Analyst — Beta",
    ]
    assert blocks[0]["bullets"] == []
    assert blocks[1]["bullets"] == ["Dashboards"]


def test_cv_source_to_markdown_from_html():
    html = "<html><body><h1>Marie Curie</h1><ul><li>Python</li></ul></body></html>"
    markdown = cv_source_to_markdown(html)
    assert "Marie Curie" in markdown
    assert "Python" in markdown


def test_cv_source_to_markdown_passthrough():
    md = "# Nom\n## Compétences\n- SQL\n"
    assert cv_source_to_markdown(md) == md
