# job_copilot

Système automatisé de mise en correspondance d'emplois et de recomposition de CV,
orchestré par **Apache Airflow**.

L'ingestion automatique des offres est pilotée par un **agent de recherche** : le DAG Airflow `search_parameters_agent` (toutes les heures) lit les paramètres de `search_parameters` et, pour chacun, ingère les offres de son URL via le même pipeline que l'ajout par URL (Playwright + LLM). Le **matching offre/profil**, la **génération de CV recomposé** et la **lettre de motivation (Markdown via LLM)** restent déclenchés **à la demande** (voir plus bas). Une offre peut aussi être ajoutée **manuellement depuis une URL**. L'ancien DAG hellowork (`job_copilot`) est conservé mais **mis en pause** (RAG hellowork obsolète).

## Architecture

Toute la logique applicative vit sous `src/` :

- `src/interfaces/scrapers/hellowork/` — scraper Hellowork (écrit des JSON dans `data/hellowork/`).
- `src/interfaces/scrapers/url/` — récupération d'une page web pour l'ajout d'offre par URL (`URLScraper.fetch_text`, Playwright headless + lxml).
- `src/services/job_parser.py` — lecture des JSON et upsert des offres dans `job_offer` (dédoublonnage par `content_hash`).
- `src/services/profile_parser.py` — parsing d'un CV uploadé (Markdown/HTML) en `candidate_profile`.
- `src/services/job_analysis.py` — matching offre × profil **via LLM** (`src/core/scoring/llm_matcher.py`), persisté dans `match_result`.
- `src/services/cv_generator.py` — génération d'un CV recomposé **via LLM** (recomposition du CV anonymisé en Markdown), persistée dans `cv_version`.
- `src/services/letter_generator.py` — génération d'une lettre de motivation **via LLM**, persistée dans `letter_version` (voir les deux passes plus bas).
- `src/services/url_job_ingestor.py` — ajout d'une offre depuis une URL (dédoublonnage, refus 409 si déjà en base), puis pipeline d'ingestion existant.
- `src/services/search_parameters_agent.py` — agent de recherche : lit `search_parameters` et ingère les offres de chaque paramètre actif (même pipeline que l'ajout par URL) ; **lancement unitaire** d'une recherche — même inactive — via `run_parameter_by_id(id)`.
- `src/core/domain/` — entités métier (`JobOffer`, `CandidateProfile`).
- `src/core/scoring/` — moteurs LLM (matching, génération CV/lettre, extraction d'offre depuis une URL) et utilitaires partagés.
- `src/core/privacy/anonymize.py` — anonymisation du CV avant envoi au LLM, réinjection des coordonnées côté serveur pour le CV.
- `src/infrastructure/db/` — modèles SQLAlchemy (reflet de `sql/tables.sql`), repositories et bootstrap du schéma.
- `src/config/` — configuration applicative (`settings.py` + `scoring.yaml`, seuil de génération `match_threshold`).
- `dags/` — DAGs Airflow : `search_parameters_agent.py` (**actif**, toutes les heures, agent de recherche) et `job_copilot.py` (hellowork : scraper → ingestion, **pausé**).

## Mise en route (dev local)

Prérequis : **Python 3.12**, [Docker](https://www.docker.com/) + Docker Compose, Node.js 20 (pour le front).

Créez un fichier `.env` à la racine (non versionné, ignoré par git) — copiez `.env.example` comme point de départ — avec au minimum :

```
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5434/job_copilot
MISTRAL_API_KEY=xxx        # matching, CV, lettre et ajout par URL (pas de fallback)
```

```bash
# 1. Dépendances (env conda ou venv)
pip install -r requirements.txt

# 2. Base de données applicative
docker compose up -d postgres-data

# 3. Appliquer le schéma (idempotent ; l'API le fait aussi au démarrage)
python -c "from src.infrastructure.db.session import engine; from src.infrastructure.db.bootstrap import ensure_schema; ensure_schema(engine)"

# 4. Uploadez le CV du candidat via l'API (un CV Markdown/HTML -> un profil candidat)
#    curl -F "file=@cv.md" http://localhost:8000/api/v1/profiles
```

Pour l'ajout d'offre par URL, installez aussi le navigateur headless :
`playwright install chromium` (déjà fait dans `api/Dockerfile`).

## Pile complète Airflow

```bash
# Construire l'image custom (dépendances applicatives). Construire sur UN service :
# `docker compose build` sans nom de service échoue (les services se disputent le tag d'image).
docker compose build airflow-apiserver

docker compose up            # scheduler, workers, webserver, etc. (utilise l'image existante)
```

Deux DAGs Airflow :

- `search_parameters_agent` (**actif**) — toutes les heures (`0 * * * *`), lit `search_parameters` et, pour chaque paramètre **actif**, ingère les offres de son URL via `URLJobIngestorService.run(url, max_offers)` (matching/CV/lettre immédiatement disponibles). Pas de pagination, `max_active_runs=1`.
- `job_copilot` (hellowork : `scrape_hellowork → ingest_job_offers`) — conservé mais **mis en pause** (le RAG hellowork est obsolète ; l'agent de recherche le remplace).

Le pipeline automatique **s'arrête après l'ingestion** : le matching, la génération de CV et de lettre restent volontairement **à la demande**.

## Interface de validation (API + web)

Deux services complètent la pile (inclus dans `docker compose up`) :

- **`api/`** (port 8000) — API FastAPI : upload de CV, matching, sélection, génération de CV **et de lettre**, ajout d'offre par URL (y compris contenu de page collé), export PDF du CV, gestion des **recherches sauvegardées** (`search_parameters` : CRUD, activation/désactivation, exécution de l'agent, **lancement unitaire** d'une recherche), statistiques. Contrat complet dans `docs/api-contract.md`.
- **`web/`** (port 3000) — interface Next.js : profils, offres (actives/archivées, tableau triable, filtres Entreprise/Source), détail d'offre (matching, génération de CV et lettre, export PDF du CV, copie de la lettre), modale d'ajout par URL (URL + slider « nombre maximal d'offres » 1→20, ou **contenu de page collé** pour débloquer les sites anti-bot), **recherches sauvegardées** (CRUD, colonnes « Max offres » et « Statut » avec toggle d'activation par ligne, bouton « Exécuter » et **triangle vert de lancement unitaire par ligne**) ; proxy serveur `/api/v1/*` vers l'API (pas de CORS côté navigateur).

```bash
# Base + API + web seulement
docker compose up -d postgres-data api web

# Itérer sur le front sans Docker (l'API est attendue sur localhost:8000)
cd web && npm install && npm run dev

# API seule (dev, depuis la racine)
pip install -r api/requirements.txt && uvicorn api.app.main:app --reload
```

L'image web est construite avec `output: standalone` ; la cible de l'API est passée au build (`build.args.API_URL`), pas à l'exécution.

### À la demande : matching, CV, lettre et ajout d'offre

Le matching, la génération de CV et de lettre ne sont **pas** automatiques : ils sont déclenchés à la demande via l'API (`api/`). Enchaînement type :

1. `POST /api/v1/profiles` (multipart `file`) — uploade un CV (Markdown/HTML) → un nouveau `candidate_profile` (nouvel id), actif s'il est le premier. Activation manuelle : `PUT /profiles/{id}/activate` (un seul profil actif ; le profil actif ne peut pas être désactivé — il faut d'abord en activer un autre). Renommage : `PATCH /profiles/{id}`. **Pas de suppression**.
2. `POST /api/v1/matching/run` `{job_offer_id, candidate_profile_id?}` — calcule le matching de l'offre (score, forces/faiblesses, compétences manquantes) → `match_result`.
3. `POST /api/v1/cvs/generate` `{job_offer_id, candidate_profile_id?}` — génère le CV recomposé → `cv_version` (un seul par couple offre/profil ; export PDF via `GET /cvs/{id}/pdf`).
4. `POST /api/v1/letters/generate` `{job_offer_id, candidate_profile_id?}` — génère la lettre de motivation → `letter_version`.
5. `POST /api/v1/job-offers/from-url` `{url, max_offers, source?}` — ajoute une offre depuis une URL (Playwright + LLM). Le champ optionnel `source` fournit un **contenu de page collé** qui **remplace le fetch Playwright** (offre unique, l'URL n'est jamais récupérée et reste la clé de dédoublonnage) — débloque les sites protégés par un anti-bot. Pour une **offre unique**, le contenu est extrait par le LLM et dédoublonné sur l'URL soumise. Pour une **liste d'offres**, le LLM ne renvoie que les URLs ; celles déjà en base (colonne `url`) sont ignorées, et jusqu'à `max_offers` offres **nouvelles** (1→20 défaut 5) sont récupérées individuellement et ingérées. `201` + `{offers, added, already_present}`. `409` si la page est une **offre unique** déjà en base, `422` si la page n'est pas une offre exploitable (page non-offre, offre indisponible, ou site protégé par un anti-bot sans contenu collé — voir **Limites connues**), `502` si le LLM est indisponible.
6. `POST /api/v1/search-parameters/run` — exécute immédiatement l'agent de recherche (même pipeline que le DAG) et retourne le résumé de l'ingestion (offres ajoutées / déjà présentes, échecs par catégorie). CRUD des recherches sauvegardées : `GET/POST /search-parameters`, `PATCH /search-parameters/{id}` (dont `max_offers` 1→20, défaut 5), `DELETE /search-parameters/{id}`, `PUT /search-parameters/{id}/activate` / `/deactivate` — une recherche **inactive** est ignorée par l'agent. **Lancement unitaire** : `POST /search-parameters/{id}/run` exécute une seule ligne, **même inactive** (test ponctuel, le statut est inchangé) ; `404` si l'id est inconnu.

Toutes ces opérations appellent le **LLM Mistral** (clé `MISTRAL_API_KEY` dans `.env`) : sans clé ou en cas de panne du LLM, l'API répond `502` (pas de fallback).

- **Matching** : `mistral-small-latest`, sur le **CV brut anonymisé** (jamais une structure parsée).
- **Génération CV en une passe** : **recomposition ciblée** sur `mistral-large-latest` — réorganiser, condenser et reformuler légèrement les informations déjà présentes dans le CV socle pour mettre en avant celles les plus pertinentes pour l'offre, sans modifier les faits, le niveau de preuve, l'identité professionnelle, les responsabilités ou le niveau d'expertise — avec **fidélité factuelle stricte** (le CV socle anonymisé est l'unique source de vérité, aucune invention). La pass 2 « humaine » est **désactivée** pour le CV. La **lettre**, elle, reste **en deux passes** : pass 1 de rédaction (`mistral-small-latest`), puis pass 2 de réécriture « humaine » sur `mistral-large-latest` ; un échec de la pass 2 conserve la lettre de la pass 1.
- **Anonymisation** : le LLM ne reçoit jamais les coordonnées. Pour le CV, le serveur **réinjecte** nom, email, téléphone, LinkedIn dans un en-tête ; la lettre, elle, **reste anonyme** (aucune réinjection).

Le contrat complet de l'API est dans `docs/api-contract.md`.

## Limites connues

L'ajout d'offres par URL et l'agent de recherche passent par un navigateur headless (Playwright). Les sites protégés par un **anti-bot** peuvent bloquer ce navigateur et renvoyer une page sans offre exploitable → l'API répond `422` « page sans offre », même pour une offre valide. Constaté sur :

- **Indeed** — Cloudflare Turnstile interactif (« vérifiez que vous êtes humain ») ;
- **APEC** — DataDome : les API d'offre (`/cms/webservices/offre/public?numeroOffre=…`) renvoient `403` au navigateur headless, la page affiche alors « l'offre n'est plus disponible » (fallback du SPA, pas la réalité).

Il ne s'agit pas d'une erreur de classification : c'est l'anti-bot qui refuse la session. **Aucun contournement n'est implémenté** (problème connu et documenté).

## Tests

```bash
python -m pytest tests/ -q -m "not integration"  # tests unitaires (aucune base ni Docker)
python -m pytest tests/ -q -m integration        # tests d'intégration (conteneur PostgreSQL jetable via Docker)
python -m pytest tests/ -q                       # suite complète
```

Les tests d'intégration démarrent un **conteneur PostgreSQL éphémère** (`postgres:16`, fixture `docker_postgres` de `conftest.py`), détruit à la fin ; la base de dev n'est jamais touchée. Docker indisponible → ils sont ignorés (`skip`). Le LLM est **mocké** (aucune clé API requise).

Front (depuis `web/`) :

```bash
npm test          # vitest + Testing Library (exécution unique)
npm run build     # build Next.js (vérification TypeScript)
```

## Intégration continue

`.github/workflows/ci.yml` (GitHub Actions) vérifie à chaque commit que le nouveau code ne casse rien :

- **push** (toute branche) → tests unitaires Python + tests vitest + build Next.js ;
- **pull request** → en plus, les tests d'intégration (conteneur PostgreSQL jetable).

Le LLM étant mocké, aucun secret n'est nécessaire dans la CI.
