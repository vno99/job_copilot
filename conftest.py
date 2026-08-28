# Garantit que la racine du projet est sur sys.path pour pytest,
# afin que les imports ``src.*`` soient résolus de façon fiable.

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Base de test jetable (conteneur PostgreSQL Docker)
# ---------------------------------------------------------------------------
# Les tests d'intégration tournent contre un conteneur ``postgres:16`` éphémère,
# démarré pour la session de test et détruit à la fin (``--rm``). La base
# applicative de dev (``postgres-data``/``job_copilot``) n'est jamais touchée :
# plus de ``CREATE DATABASE`` ni de redirection de ``DATABASE_URL`` vers
# ``job_copilot_test`` sur le serveur existant.
#
# Paramètres calqués sur le service ``postgres-data`` de ``docker-compose.yaml``
# (image, user, mot de passe, nom de base).
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

_DOCKER_IMAGE = "postgres:16"
_PG_USER = "user"
_PG_PASSWORD = "password"
_PG_DB = "job_copilot"


class _PgContainer:
    """Référence vers le conteneur PostgreSQL de test."""

    def __init__(self, name: str, host_port: int):
        self.name = name
        self.host_port = host_port

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{_PG_USER}:{_PG_PASSWORD}"
            f"@127.0.0.1:{self.host_port}/{_PG_DB}"
        )


def _run_docker(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    """Exécute une commande ``docker`` en sous-processus (sans lever d'erreur)."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _docker_available() -> bool:
    """True si le daemon Docker répond (le CLI ``docker`` suffit au pilotage)."""
    try:
        return _run_docker(["info"], timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def _start_pg_container() -> _PgContainer:
    """Démarre un conteneur ``postgres:16`` jetable et retourne sa référence.

    Le port hôte est publié automatiquement par Docker (``127.0.0.1::5432``),
    puis récupéré via ``docker port``. En cas d'échec après ``docker run``,
    le conteneur est nettoyé avant de remonter l'erreur (RuntimeError).
    """
    name = f"job_copilot_test_pg_{os.getpid()}"
    # Pré-nettoyage d'un éventuel conteneur résiduel du même nom (crash précédent).
    _run_docker(["rm", "-f", name], timeout=60)

    result = _run_docker(
        [
            "run", "-d", "--rm", "--name", name,
            "-e", f"POSTGRES_USER={_PG_USER}",
            "-e", f"POSTGRES_PASSWORD={_PG_PASSWORD}",
            "-e", f"POSTGRES_DB={_PG_DB}",
            "-p", "127.0.0.1::5432",
            "--shm-size=512m",
            "--health-cmd", "pg_isready -U user -d job_copilot",
            "--health-interval", "1s",
            "--health-timeout", "2s",
            "--health-retries", "30",
            "--health-start-period", "2s",
            _DOCKER_IMAGE,
        ],
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker run a échoué : {result.stderr.strip()}")

    out = _run_docker(["port", name, "5432"]).stdout.strip()
    try:
        host_port = int(out.rsplit(":", 1)[-1])
    except (ValueError, IndexError) as exc:
        _run_docker(["rm", "-f", name], timeout=60)
        raise RuntimeError(f"Port hôte introuvable pour {name} : {out!r}") from exc
    return _PgContainer(name, host_port)


def _wait_pg_ready(name: str, timeout: float = 60.0) -> None:
    """Attend que le conteneur soit ``healthy`` (healthcheck ``pg_isready``)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _run_docker(
            ["inspect", "-f", "{{.State.Health.Status}}", name]
        ).stdout.strip()
        if status == "healthy":
            return
        time.sleep(1)
    raise RuntimeError(
        f"Le conteneur {name} n'est pas devenu healthy dans {timeout:.0f}s"
    )


def _stop_pg_container(container: _PgContainer) -> None:
    """Arrête le conteneur ; le flag ``--rm`` le supprime automatiquement."""
    _run_docker(["stop", "-t", "5", container.name], timeout=60)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: nécessite Docker (conteneur PostgreSQL jetable)"
    )


@pytest.fixture(scope="session")
def docker_postgres():
    """Conteneur PostgreSQL jetable dédié aux tests d'intégration.

    Démarre ``postgres:16`` sur un port hôte libre, re-pointe l'engine
    applicatif vers ce conteneur (``configure_database``), applique le schéma,
    puis détruit le conteneur en teardown. Les tests d'intégration sont skip si
    Docker est indisponible ou si le démarrage/la configuration échoue.
    """
    if not _docker_available():
        pytest.skip("Docker indisponible : tests d'intégration ignorés")

    container = None
    try:
        container = _start_pg_container()
        _wait_pg_ready(container.name)

        from sqlalchemy import text

        from src.infrastructure.db.bootstrap import ensure_schema
        from src.infrastructure.db.session import configure_database, get_engine

        configure_database(container.url)
        ensure_schema(get_engine())
        # Smoke test : la base répond réellement (au-delà du pg_isready).
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Base PostgreSQL de test indisponible : {exc}")
    else:
        yield
    finally:
        if container is not None:
            _stop_pg_container(container)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Remplace le LLM Mistral par une réponse déterministe hors-ligne.

    Sept branches sont servies, distinguées par leurs marqueurs (les branches de
    génération de CV, de lettre et de réécriture sont testées AVANT le matching,
    les prompts contenant ``=== PROFIL CANDIDAT ===`` ; la réécriture du CV est
    même testée AVANT la génération pass 1, son prompt contenant aussi
    ``=== ANALYSE DE COMPATIBILITÉ ===``) :

    - **Génération de CV** (``=== ANALYSE DE COMPATIBILITÉ ===``) : renvoie un
      Markdown déterministe commençant par ``# [NOM]``, pour exercer
      ``inject_contact_info`` (retrait de l'en-tête d'identité du LLM) et la
      conversion en Markdown.
    - **Lettre de motivation** (``=== LETTRE DE MOTIVATION ===``) : renvoie un
      Markdown déterministe sans coordonnées, pour exercer
      ``clean_letter_markdown`` (la lettre reste anonyme, aucune réinjection).
    - **Réécriture humanisée (lettre)** (``=== RÉÉCRITURE HUMAINE ===``) :
      renvoie un Markdown déterministe, sans coordonnées ni ``[NOM]``, terminant
      par ``Cordialement,`` — la lettre réécrite reste anonyme.
    - **Réécriture humanisée (CV)** (``=== RÉÉCRITURE HUMAINE CV ===``) : renvoie
      un Markdown déterministe contenant ``## Compétences`` et un tableau,
      commençant par ``# [NOM]`` pour exercer ``inject_contact_info``.
    - **Classification d'une page depuis une URL** (``=== OFFRE DEPUIS URL ===``) :
      renvoie un payload ``page_type "single"`` déterministe (Data Engineer H/F
      chez Acme), valide pour ``extract_page`` / ``extract_offer``.
    - **Matching** (``=== PROFIL CANDIDAT ===``) : renvoie un ``match_result``
      fixe (score, breakdown 4 critères, forces/faiblesses/compétences manquantes,
      explication), valide pour ``compute_llm_match``.
    - **Extraction de compétences** (``OFFRE À ANALYSER :``) : émet un
      ``hard_skill`` par token de l'offre, reproduisant l'ancienne whitelist pour
      que les assertions (re-tri du CV, ingestion) restent valides sans clé API.
    """
    from src.core.scoring import score_engine

    def fake_invoke(_messages) -> SimpleNamespace:
        user_prompt = _messages[-1].content
        # La réécriture humanisée du CV est testée AVANT la génération pass 1 :
        # son prompt contient aussi ``=== ANALYSE DE COMPATIBILITÉ ===`` (le
        # matching y est transmis), il ne faut pas re-brancher sur la pass 1.
        if "=== RÉÉCRITURE HUMAINE CV ===" in user_prompt:
            rewritten_cv = """# [NOM]

## Résumé
Chez Acme, le pipeline d'ingestion plantait toutes les nuits et l'équipe data
n'osait plus y toucher. J'ai reconstruit le chargement avec Airflow et Python,
ajouté des contrôles de qualité, et mis fin aux interventions en urgence.

## Compétences
| Domaine | Technologies |
|---|---|
| Langages & pipelines | Python, SQL, Airflow |

## Expérience
### Data Engineer — Acme (2020 - 2024)
Le défi : des ingestions qui s'arrêtaient sans raison. La résolution : un
pipeline Airflow fiabilisé, surveillé, avec des reprises automatiques.
"""
            return SimpleNamespace(content=rewritten_cv)

        if "=== ANALYSE DE COMPATIBILITÉ ===" in user_prompt:
            generated_cv = """# [NOM]

## Résumé
Data Engineer expérimenté.

## Compétences
- Python
- SQL
- Airflow

## Expérience
### Data Engineer — Acme (2020 - 2024)
- Pipelines d'ingestion
"""
            return SimpleNamespace(content=generated_cv)

        if "=== LETTRE DE MOTIVATION ===" in user_prompt:
            generated_letter = """## Objet
Candidature au poste de Data Engineer

Madame, Monsieur,

Fort de plusieurs années d'expérience en ingestion de données avec Python et
Airflow, je souhaite mettre mon expertise au service de votre équipe.

Cordialement,
"""
            return SimpleNamespace(content=generated_letter)

        # La 2e passe de la lettre et du CV (réécriture) est testée AVANT le
        # matching : les prompts de réécriture contiennent aussi ``=== PROFIL
        # CANDIDAT ===``.
        if "=== RÉÉCRITURE HUMAINE ===" in user_prompt:
            rewritten_letter = """## Objet
Candidature au poste de Data Engineer

Madame, Monsieur,

On m'a souvent dit que je parlais de mes pipelines comme d'autres de leurs
projets de bricolage. C'est un peu vrai : avec Airflow et Python, j'ai passé
des semaines à rendre fiables des ingestions que personne ne regardait.

Ce qui m'a plu dans votre offre, c'est de voir que la donnée est un enjeu
d'équipe, pas un simple tuyau. J'espère que mon profil pourra vous intéresser.

Cordialement,
"""
            return SimpleNamespace(content=rewritten_letter)

        if "=== OFFRE DEPUIS URL ===" in user_prompt:
            payload = {
                "page_type": "single",
                "offer": {
                    "title": "Data Engineer H/F",
                    "company": "Acme",
                    "location": "Paris - 75",
                    "contract_type": "CDI",
                    "description": "Python SQL Databricks",
                    "published_date": "2026-05-22",
                    "experience": "3 ans",
                    "diploma": "Bac +5",
                },
            }
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

        if "=== PROFIL CANDIDAT ===" in user_prompt:
            payload = {
                "score": 70,
                "score_breakdown": {
                    "title_score": 0.8,
                    "skills_score": 0.7,
                    "experience_score": 0.6,
                    "education_score": 0.5,
                },
                "strengths": ["Maîtrise de Python et SQL"],
                "weaknesses": ["Pas d'expérience Databricks"],
                "missing_skills": ["databricks"],
                "explanation": (
                    "Mettez en avant vos pipelines Airflow et compensez le "
                    "manque d'expérience Databricks par des projets similaires."
                ),
            }
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

        # Entre le marqueur d'offre et l'exemple « JSON ATTENDU », pour ne pas
        # capturer les mots-clés du bloc d'exemple du prompt.
        description = user_prompt.split("OFFRE À ANALYSER :", 1)[-1].split("JSON ATTENDU", 1)[0]
        names = [
            token.strip('.,;:()[]{}"')
            for token in description.replace(",", " ").split()
            if token.strip('.,;:()[]{}"')
        ]
        payload = {
            "hard_skills": [
                {"name": n, "category": "autre", "level": "non précisé", "mandatory": False}
                for n in names
            ],
            "soft_skills": [],
            "certifications": [],
        }
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(score_engine, "LLM", SimpleNamespace(invoke=fake_invoke))
    # Instances dédiées : patcher les cinq, sinon la génération de CV/lettre
    # lève « clé absente » (CV_GENERATION_LLM / GENERATION_LLM None), la pass 2
    # de la lettre (HUMANIZE_LLM None) serait silencieusement court-circuitée —
    # le chemin de réécriture ne serait jamais exercé — et l'extraction d'offre
    # depuis une URL (URL_SCRAPER_LLM None) lèverait LLMExtractionError.
    monkeypatch.setattr(
        score_engine, "GENERATION_LLM", SimpleNamespace(invoke=fake_invoke)
    )
    monkeypatch.setattr(
        score_engine, "CV_GENERATION_LLM", SimpleNamespace(invoke=fake_invoke)
    )
    monkeypatch.setattr(
        score_engine, "HUMANIZE_LLM", SimpleNamespace(invoke=fake_invoke)
    )
    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=fake_invoke)
    )
