# Job Copilot

[![Python Version](https://img.shields.io/badge/python-3.12+-yellow.svg)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/next.js-16+-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16+-blue.svg)](https://www.postgresql.org/)
[![Airflow](https://img.shields.io/badge/-Airflow%203.1.8-017CEE?style=flat&logo=apache-airflow)](https://airflow.apache.org/)

Système automatisé de mise en correspondance d'emplois et recomposition de CV, orchestré par **Apache Airflow**.

Le pipeline automatique est piloté par l'**agent de recherche** (`search_parameters_agent`, toutes les heures) : il lit `search_parameters` et ingère les offres actives via `URLJobIngestorService`. L'ancien DAG `job_copilot` (hellowork) est conservé mais **en pause**.

Le **matching**, la **génération de CV** et la **lettre de motivation** (Markdown via LLM) sont déclenchés **à la demande** depuis l'interface.

## Architecture

- `src/` — logique applicative (scrapers, services, LLM, DB).
- `api/` — FastAPI (port 8000) : upload CV, matching, CV/lettre, ajout par URL, recherches sauvegardées.
- `web/` — Next.js (port 3000) : interface de validation.
- `dags/` — `search_parameters_agent` (actif) et `job_copilot` (pausé).
- `docs/api-contract.md` — contrat complet de l'API.

## Démarrage (dev)

```bash
cp .env.example .env  # renseigner DATABASE_URL et OPENROUTER_API_KEY
docker compose up -d postgres-data
python -c "from src.infrastructure.db.session import engine; from src.infrastructure.db.bootstrap import ensure_schema; ensure_schema(engine)"
```

API seule : `cd api && pip install -r requirements.txt && uvicorn api.app.main:app --reload` (port 8000). Front : `cd web && npm run dev` (port 3000).

## Pipeline à la demande

1. `POST /api/v1/profiles` — upload CV (Markdown/HTML) → nouveau profil.
2. `POST /api/v1/matching/run` — matching offre × profil.
3. `POST /api/v1/cvs/generate` — CV recomposé (Markdown, anonymisé, réinjecté côté serveur, **une passe**, pass 2 désactivée).
4. `POST /api/v1/letters/generate` — lettre de motivation (**deux passes** : rédaction puis réécriture humaine, anonyme).
5. `POST /api/v1/job-offers/from-url` — ajout d'offre depuis une URL (`max_offers` 1→20, défaut 5). Le champ `source` (contenu collé) remplace le fetch Playwright et débloque les sites anti-bot (offre unique, dédoublonnage sur URL).
6. `POST /api/v1/search-parameters/run` — exécution immédiate de l'agent (tous actifs). `POST /search-parameters/{id}/run` — lancement unitaire d'une recherche, même inactive (test ponctuel).

Toutes les opérations LLM passent par **OpenRouter** (`OPENROUTER_API_KEY`). Sans clé ou panne LLM → `502` (pas de fallback). Modèles : `OPENROUTER_LLM_MODEL_SMALL` (défaut `mistral/mistral-small-latest`) et `OPENROUTER_LLM_MODEL_LARGE` (défaut `mistral/mistral-large-latest`).

## Tests

```bash
python -m pytest tests/ -q -m "not integration"  # unitaires
python -m pytest tests/ -q -m integration         # intégration (Docker)
# Front : cd web && npm test
```

Les tests d'intégration utilisent un conteneur PostgreSQL éphémère (`postgres:16`), détruit en fin de suite.

## Limites connues

Le navigateur headless (Playwright) est bloqué par certains anti-bot : **Indeed** (Cloudflare Turnstile), **APEC** (DataDome) → `422`. Aucun contournement automatisé n'est implémenté. Le contenu collé (`source`) débloque ces cas (l'utilisateur fournit le texte).
