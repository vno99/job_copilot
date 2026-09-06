from pathlib import Path
from unittest.mock import patch, MagicMock

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


def test_extract_headline_plain_name_line():
    """Un nom en premiere ligne (sans # ni **) est retenu comme headline."""
    md = """Jean Dupont

## Compétences
- Python
"""
    from src.services.profile_parser import _extract_headline
    result = _extract_headline(md)
    assert result == "Jean Dupont"


def test_extract_headline_prefers_heading_over_plain():
    """Un titre # (non-section) est prefere au nom en ligne simple."""
    md = """Jean Dupont

# Lead Engineer

## Compétences
"""
    from src.services.profile_parser import _extract_headline
    result = _extract_headline(md)
    assert result == "Lead Engineer"


def test_extract_skills_skips_empty_items():
    """Un tiret avec uniquement des espaces est ignore."""
    from src.services.profile_parser import _extract_skills
    lines = ["- Python", "-   ", "- SQL"]
    result = _extract_skills(lines)
    assert "Python" in result
    assert "SQL" in result
    assert "" not in result
    assert "   " not in result


def test_extract_skills_with_category_prefix():
    """Une competence precedee de **Categorie** a le prefixe retire."""
    from src.services.profile_parser import _extract_skills
    lines = ["-  **Data Engineering** : Python, SQL, Airflow"]
    result = _extract_skills(lines)
    assert "Python" in result
    assert "SQL" in result
    assert "Airflow" in result
    assert "Data Engineering" not in result


def test_parse_experience_blocks_no_heading_bold():
    """Une ligne sans # ni ** avant la premiere puce cree un bloc sans titre."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["Tech Lead", "- Pipeline Airflow", "- SQL"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Tech Lead" in blocks[0]["title"]
    assert "Pipeline Airflow" in blocks[0]["bullets"]


def test_parse_experience_blocks_period_attached_no_bullets():
    """Une periode (01/2022) rattachee au titre, sans puces, fonctionne."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["**Data Engineer**", "**01/2022 - 06/2025**"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "01/2022" in blocks[0]["title"]
    assert "06/2025" in blocks[0]["title"]


def test_parse_experience_blocks_desc_line_before_bullets():
    """Une ligne descriptive (entreprise / periode) avant la premiere puce
    complete le titre du poste."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["**Data Engineer**", "Acme Corp", "- Pipeline"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Data Engineer" in blocks[0]["title"]
    assert "Acme Corp" in blocks[0]["title"]
    assert "Pipeline" in blocks[0]["bullets"]


def test_parse_experience_blocks_stack_line_after_bullets():
    """Une ligne de Stack apres les puces est conservee comme puce."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = [
        "**Tech Lead**",
        "- Migration cloud",
        "**Stack** : Java 17, Spring Boot",
    ]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Migration cloud" in blocks[0]["bullets"]
    assert "Stack : Java 17, Spring Boot" in blocks[0]["bullets"]


def test_profile_parser_service_generate_profile_name_unique(tmp_path):
    """_generate_profile_name ajoute un suffixe horodate si le nom de base existe."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    from unittest.mock import MagicMock

    service = ProfileParserService()

    call_count = [0]

    def fake_get_by_name(session, name):
        call_count[0] += 1
        # Premiere appel -> nom pris, deuxieme appel -> encore pris,
        # troisieme -> libre
        if call_count[0] <= 2:
            return MagicMock(profile_name=name)
        return None

    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", fake_get_by_name):
        name = service._generate_profile_name(mock_session, "mon_cv")

    assert name.startswith("mon_cv_")
    assert call_count[0] >= 2


def test_cv_source_to_markdown_does_not_convert_non_html():
    """cv_source_to_markdown ne convertit pas du texte brut."""
    from src.services.profile_parser import cv_source_to_markdown
    md = "# Compétences\n- Python\n- SQL"
    result = cv_source_to_markdown(md)
    assert result == md


def test_cv_source_to_markdown_detects_html_without_body():
    """Un fichier HTML sans <body> est quand meme converti."""
    from src.services.profile_parser import cv_source_to_markdown
    html = "<html><head><title>CV</title></head><p>Jean Dupont</p></html>"
    result = cv_source_to_markdown(html)
    assert "Jean Dupont" in result


def test_cv_source_to_markdown_from_path(tmp_path):
    """Ligne 29 : cv_source_to_markdown lit un Path et convertit le HTML."""
    from src.services.profile_parser import cv_source_to_markdown
    cv_file = tmp_path / "cv.html"
    cv_file.write_text("<html><body><p>Marie Curie</p></body></html>", encoding="utf-8")
    result = cv_source_to_markdown(cv_file)
    assert "Marie Curie" in result


def test_generate_profile_name_returns_base_when_free():
    """Ligne 241 : quand le nom de base n'est pas pris, il est retourne."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", return_value=None):
        name = ProfileParserService._generate_profile_name(mock_session, "mon_cv")
    assert name == "mon_cv"


def test_generate_profile_name_falls_back_to_suffix_when_base_taken():
    """Quand le nom de base est pris, un suffixe horodate est ajoute."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", side_effect=[
        MagicMock(profile_name="mon_cv"),
        None
    ]):
        name = ProfileParserService._generate_profile_name(mock_session, "mon_cv")
    assert name.startswith("mon_cv_")


def test_extract_headline_plain_name_line():
    """Un nom en premiere ligne (sans # ni **) est retenu comme headline."""
    md = """Jean Dupont

## Compétences
- Python
"""
    from src.services.profile_parser import _extract_headline
    result = _extract_headline(md)
    assert result == "Jean Dupont"


def test_extract_headline_prefers_heading_over_plain():
    """Un titre # (non-section) est prefere au nom en ligne simple."""
    md = """Jean Dupont

# Lead Engineer

## Compétences
"""
    from src.services.profile_parser import _extract_headline
    result = _extract_headline(md)
    assert result == "Lead Engineer"


def test_extract_skills_skips_empty_items():
    """Un tiret avec uniquement des espaces est ignore."""
    from src.services.profile_parser import _extract_skills
    lines = ["- Python", "-   ", "- SQL"]
    result = _extract_skills(lines)
    assert "Python" in result
    assert "SQL" in result
    assert "" not in result
    assert "   " not in result


def test_extract_skills_with_category_prefix():
    """Une competence precedee de **Categorie** a le prefixe retire."""
    from src.services.profile_parser import _extract_skills
    lines = ["-  **Data Engineering** : Python, SQL, Airflow"]
    result = _extract_skills(lines)
    assert "Python" in result
    assert "SQL" in result
    assert "Airflow" in result
    assert "Data Engineering" not in result


def test_parse_experience_blocks_no_heading_bold():
    """Une ligne sans # ni ** avant la premiere puce cree un bloc sans titre."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["Tech Lead", "- Pipeline Airflow", "- SQL"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Tech Lead" in blocks[0]["title"]
    assert "Pipeline Airflow" in blocks[0]["bullets"]


def test_parse_experience_blocks_period_attached_no_bullets():
    """Une periode (01/2022) rattachee au titre, sans puces, fonctionne."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["**Data Engineer**", "**01/2022 - 06/2025**"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "01/2022" in blocks[0]["title"]
    assert "06/2025" in blocks[0]["title"]


def test_parse_experience_blocks_desc_line_before_bullets():
    """Une ligne descriptive (entreprise / periode) avant la premiere puce
    complete le titre du poste."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = ["**Data Engineer**", "Acme Corp", "- Pipeline"]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Data Engineer" in blocks[0]["title"]
    assert "Acme Corp" in blocks[0]["title"]
    assert "Pipeline" in blocks[0]["bullets"]


def test_parse_experience_blocks_stack_line_after_bullets():
    """Une ligne de Stack apres les puces est conservee comme puce."""
    from src.services.profile_parser import _parse_experience_blocks
    lines = [
        "**Tech Lead**",
        "- Migration cloud",
        "**Stack** : Java 17, Spring Boot",
    ]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Migration cloud" in blocks[0]["bullets"]
    assert "Stack : Java 17, Spring Boot" in blocks[0]["bullets"]


def test_profile_parser_service_generate_profile_name_unique(tmp_path):
    """_generate_profile_name ajoute un suffixe horodate si le nom de base existe."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    from unittest.mock import MagicMock

    service = ProfileParserService()

    call_count = [0]

    def fake_get_by_name(session, name):
        call_count[0] += 1
        # Premiere appel -> nom pris, deuxieme appel -> encore pris,
        # troisieme -> libre
        if call_count[0] <= 2:
            return MagicMock(profile_name=name)
        return None

    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", fake_get_by_name):
        name = service._generate_profile_name(mock_session, "mon_cv")

    assert name.startswith("mon_cv_")
    assert call_count[0] >= 2


def test_cv_source_to_markdown_does_not_convert_non_html():
    """cv_source_to_markdown ne convertit pas du texte brut."""
    from src.services.profile_parser import cv_source_to_markdown
    md = "# Compétences\n- Python\n- SQL"
    result = cv_source_to_markdown(md)
    assert result == md


def test_cv_source_to_markdown_detects_html_without_body():
    """Un fichier HTML sans <body> est quand meme converti."""
    from src.services.profile_parser import cv_source_to_markdown
    html = "<html><head><title>CV</title></head><p>Jean Dupont</p></html>"
    result = cv_source_to_markdown(html)
    assert "Jean Dupont" in result


def test_cv_source_to_markdown_from_path(tmp_path):
    """Ligne 29 : cv_source_to_markdown lit un Path et convertit le HTML."""
    from src.services.profile_parser import cv_source_to_markdown
    cv_file = tmp_path / "cv.html"
    cv_file.write_text("<html><body><p>Marie Curie</p></body></html>", encoding="utf-8")
    result = cv_source_to_markdown(cv_file)
    assert "Marie Curie" in result


def test_generate_profile_name_returns_base_when_free():
    """Ligne 241 : quand le nom de base n'est pas pris, il est retourne."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", return_value=None):
        name = ProfileParserService._generate_profile_name(mock_session, "mon_cv")
    assert name == "mon_cv"


def test_generate_profile_name_falls_back_to_suffix_when_base_taken():
    """Quand le nom de base est pris, un suffixe horodate est ajoute."""
    from src.services.profile_parser import ProfileParserService
    from src.infrastructure.db.repositories import candidate_profile_repository
    mock_session = MagicMock()
    with patch.object(candidate_profile_repository, "get_by_name", side_effect=[
        MagicMock(profile_name="mon_cv"),
        None
    ]):
        name = ProfileParserService._generate_profile_name(mock_session, "mon_cv")
    assert name.startswith("mon_cv_")

