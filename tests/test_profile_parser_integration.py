"""Tests d'intégration pour src/services/profile_parser.py.

Ces tests exercent ProfileParserService.run_from_content avec une vraie base
PostgreSQL (conteneur éphémère via docker_postgres) pour couvrir les lignes
270-295 (insertion en base, is_active, dédoublonnage de nom).
"""
import uuid
import pytest
from sqlalchemy import text

from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.repositories import candidate_profile_repository
from src.infrastructure.db.session import session_scope, get_engine


# =============================================================================
# Fixture de nettoyage - utilise directement get_engine sans dépendre de docker_postgres
# =============================================================================

def _cleanup_int_profiles():
    """Nettoie les profils créés par les tests (indépendant du fixture docker_postgres)."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM candidate_profile WHERE profile_name LIKE 'IntTest%'"))
    except Exception:
        pass  # Ignore les erreurs de cleanup


# =============================================================================
# Tests d'intégration : ProfileParserService.run_from_content
# =============================================================================

@pytest.mark.integration()
def test_run_from_content_first_profile_becomes_active(docker_postgres):
    """Quand aucun profil n'existe, le premier profil uploadé devient actif."""
    _cleanup_int_profiles()  # Nettoyer avant

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest First {uuid.uuid4().hex[:8]}"
    content = """# Jean Dupont

## Résumé
Data Engineer

## Compétences
- Python
- SQL
"""
    profile_id = service.run_from_content(content, profile_name=unique_name)

    assert isinstance(profile_id, int)
    with session_scope() as session:
        profile = candidate_profile_repository.get_active(session)
        assert profile is not None
        assert profile.id == profile_id
        assert profile.profile_name == unique_name

    _cleanup_int_profiles()  # Nettoyer après


@pytest.mark.integration()
def test_run_from_content_second_profile_is_inactive(docker_postgres):
    """Le second profil uploadé est inactif (un seul actif à la fois)."""
    _cleanup_int_profiles()  # Nettoyer avant

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    name1 = f"IntTest Premier {uuid.uuid4().hex[:8]}"
    name2 = f"IntTest Deuxieme {uuid.uuid4().hex[:8]}"
    content1 = "# Int Premier\n## Compétences\n- Python"
    content2 = "# Int Deuxième\n## Compétences\n- SQL"

    id1 = service.run_from_content(content1, profile_name=name1)
    id2 = service.run_from_content(content2, profile_name=name2)

    with session_scope() as session:
        active = candidate_profile_repository.get_active(session)
        assert active is not None
        assert active.id == id1, f"Expected active.id={id1} but got {active.id} (name={active.profile_name})"
        # Le second n'est pas actif
        all_profiles = candidate_profile_repository.list_all(session)
        active_ids = [p.id for p in all_profiles if p.is_active]
        assert len(active_ids) == 1, f"Expected 1 active profile, got {len(active_ids)}: {[p.profile_name for p in all_profiles if p.is_active]}"
        assert active_ids[0] == id1

    _cleanup_int_profiles()  # Nettoyer après


@pytest.mark.integration()
def test_run_from_content_raw_content_preserved(docker_postgres):
    """Le contenu brut du CV est conservé dans cv_raw_json.raw_content."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Raw {uuid.uuid4().hex[:8]}"
    raw_content = """# Marie Curie

## Résumé
Physicienne

## Compétences
- Physique
- Mathématiques
"""
    profile_id = service.run_from_content(raw_content, profile_name=unique_name)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None
        assert row.cv_raw_json is not None
        assert "Marie Curie" in row.cv_raw_json.get("raw_content", "")

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_skills_extracted(docker_postgres):
    """Les compétences du CV sont extraites et stockées."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Skills {uuid.uuid4().hex[:8]}"
    content = """# Test Skills

## Compétences
- Python
- SQL
- Airflow, dbt
"""
    profile_id = service.run_from_content(content, profile_name=unique_name)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None
        assert isinstance(row.skills, list)
        assert len(row.skills) >= 3

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_experiences_parsed(docker_postgres):
    """Les expériences professionnelles sont extraites et structurées."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Experience {uuid.uuid4().hex[:8]}"
    content = """# Jean

## Expérience

**Data Engineer — Acme (2020-2024)**
- Pipeline Airflow
- SQL

**Analyste — Beta (2018-2020)**
- Excel
"""
    profile_id = service.run_from_content(content, profile_name=unique_name)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None
        assert isinstance(row.experiences, list)
        assert len(row.experiences) >= 1

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_education_parsed(docker_postgres):
    """La formation est extraite."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Education {uuid.uuid4().hex[:8]}"
    content = """# Jean

## Formation
- Master Informatique — Paris (2015-2017)
- Licence Informatique — Paris (2012-2015)
"""
    profile_id = service.run_from_content(content, profile_name=unique_name)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None
        assert isinstance(row.education, list)
        assert len(row.education) >= 1

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_headline_extracted(docker_postgres):
    """Le headline (titre/poste) est extrait."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Headline {uuid.uuid4().hex[:8]}"
    content = """# Jean Dupont

## Résumé
Ingénieur
"""
    profile_id = service.run_from_content(content, profile_name=unique_name)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None
        assert row.headline is not None

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_auto_name_when_no_profile_name(docker_postgres):
    """Quand profile_name est absent, un nom est généré depuis filename."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    content = "# Test\n## Compétences\n- Python"
    profile_id = service.run_from_content(content, filename=f"mon_cv_test_{uuid.uuid4().hex[:6]}.md")

    assert isinstance(profile_id, int)
    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert "mon_cv_test" in row.profile_name

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_with_html_input(docker_postgres):
    """Le service accepte aussi du HTML (converti en Markdown)."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest HTML {uuid.uuid4().hex[:8]}"
    html_content = """<html><body>
<h1>Jean Dupont</h1>
<h2>Résumé</h2>
<p>Data Engineer</p>
<h2>Compétences</h2>
<ul><li>Python</li><li>SQL</li></ul>
</body></html>"""
    profile_id = service.run_from_content(html_content, profile_name=unique_name)

    assert isinstance(profile_id, int)
    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert row is not None

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_source_path_stored(docker_postgres):
    """Le chemin source du fichier est stocké dans cv_raw_json."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Source {uuid.uuid4().hex[:8]}"
    filename = f"cv_final_v3_test_{uuid.uuid4().hex[:6]}.pdf"
    content = "# Test\n## Compétences\n- Python"
    profile_id = service.run_from_content(content, filename=filename)

    with session_scope() as session:
        row = session.get(CandidateProfileModel, profile_id)
        assert filename in row.cv_raw_json.get("source_path", "")

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_filename_conflict_generates_unique_name(docker_postgres):
    """Quand le nom dérivé du filename est déjà pris, un nom unique est généré."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    # Utiliser le même filename pour les deux → le service doit générer un nom unique
    shared_filename = f"cv_test_{uuid.uuid4().hex[:6]}.md"
    content = "# Test\n## Compétences\n- Python"

    # Créer un premier profil (nom dérivé du filename)
    id1 = service.run_from_content(content, filename=shared_filename)
    name1 = shared_filename.replace(".md", "").replace(".pdf", "")

    # Créer un second avec le même filename → génère un nom différent
    id2 = service.run_from_content(content, filename=shared_filename)

    assert id1 != id2
    with session_scope() as session:
        all_profiles = candidate_profile_repository.list_all(session)
        names = [p.profile_name for p in all_profiles]
        # Le premier profil a le nom de base
        assert any(name1 in n for n in names)
        # Le second a un suffixe ajouté
        other_names = [n for n in names if n == name1]
        assert len(other_names) == 1, f"Expected 1 base name, got {other_names}"

    _cleanup_int_profiles()


@pytest.mark.integration()
def test_run_from_content_final_cleanup(docker_postgres):
    """Test final avec nettoyage des données après exécution."""
    _cleanup_int_profiles()

    from src.services.profile_parser import ProfileParserService

    service = ProfileParserService()
    unique_name = f"IntTest Cleanup {uuid.uuid4().hex[:8]}"
    profile_id = service.run_from_content("# Test\n## Compétences\n- Python", profile_name=unique_name)
    assert isinstance(profile_id, int)

    _cleanup_int_profiles()
