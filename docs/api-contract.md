# Contrat d'API — job_copilot

Contrat de l'interface web (Next.js) avec le backend Python (FastAPI).
Ce document est la référence : l'API et le front doivent s'y conformer.

## Principes généraux

- **Base path** : `/api/v1` — service FastAPI séparé, consommé par `web/`.
- **CORS** : autorisé pour l'origine du front (`web/`) ; sinon proxy via rewrites Next.js.
- **Profil actif** : un seul profil est actif à la fois, désigné par `is_active` dans
  `candidate_profile`. L'API le résout côté serveur. `candidate_profile_id` est
  **optionnel partout** : s'il est absent, le profil actif est utilisé.
- **Actions synchrones** : le matching **et la génération de CV et de lettre de
  motivation** appellent le LLM Mistral (clé `MISTRAL_API_KEY`) et restent
  synchrones (pas de file de jobs en v1). La génération de **CV** (pass 1) utilise
  l'instance dédiée `CV_GENERATION_LLM` (**`mistral-large-latest`**) ; le matching,
  la **lettre** (pass 1) et la classification de page par URL restent sur
  `mistral-small-latest`. La **pass 2 de la lettre** (réécriture humanisée) utilise
  l'instance dédiée `HUMANIZE_LLM` (`mistral-large-latest`). La génération
  reformule le CV existant **anonymisé** en **Markdown** (mêmes rubriques et mise
  en forme, points forts mis en avant) ; la lettre de motivation est rédigée
  depuis l'offre et le CV (généré, sinon brut).
  Les coordonnées du candidat sont réinjectées côté serveur dans un **en-tête du CV** généré ;
  la **lettre de motivation reste anonyme** (aucune coordonnée réelle n'est réinjectée).
  L'**ajout d'une offre par URL** (`POST /job-offers/from-url`) est lui aussi synchrone :
  récupération de la page (Playwright) puis classification par le LLM (`mistral-small-latest`).
  Une page peut contenir une **offre unique** (comportement historique, contenu extrait par le
  LLM, dédoublonnage sur l'URL soumise) ou une **liste d'offres** : le LLM ne renvoie alors que
  les **URLs** des offres (dans l'ordre de la page). Les URLs déjà en base (colonne `url`,
  indépendamment de la source) sont **ignorées sans mise à jour**, puis chacune des
  `max_offers` premières URLs **nouvelles** est récupérée individuellement (fetch Playwright +
  extraction mono-offre LLM) et ingérée via le pipeline existant (chaque offre porte son URL
  individuelle, clé de dédoublonnage). Un échec de récupération individuel est ignoré.
  Le champ **`source` (optionnel)** de `from-url` porte le **contenu de la page collé** par
  l'utilisateur : présent, il déclenche la même ingestion **offre unique**, mais le contenu
  (HTML du code source ou texte) **remplace le fetch Playwright** — l'URL fournie n'est jamais
  récupérée, elle sert de clé de dédoublonnage et de source d'ingestion. Débloque les sites
  anti-bot (Indeed, APEC) sans contournement automatisé (c'est l'utilisateur qui colle le
  contenu).
- **Erreurs** : `404` (ressource introuvable), `409` (conflit métier, ex. génération de CV
  ou de lettre sans `match_result`, **matching / sélection / génération de CV ou de lettre /
  suppression de document sur une offre archivée**, ou **URL d'offre déjà en base** à
  l'ajout par URL — avec ou sans contenu collé),
  `422` (validation pydantic ; URL d'offre invalide — non-http(s) —, page non-offre à
  l'ajout par URL, ou **contenu collé sans offre unique** — une page de liste répond 422 —
  à `from-url` avec `source`, avec le motif du refus précisé dans le message quand le LLM
  l'a identifié — ex. « l'offre n'est plus disponible sur le site »), `404` si le
  profil actif n'est pas chargé,
  `413` (contenu collé au-delà de 2 000 000 de caractères à `from-url` avec `source`),
  `502` (LLM Mistral indisponible pendant un matching, une génération de CV ou de lettre,
  ou l'extraction d'une offre depuis une URL ou un contenu collé).

## Profil

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| GET | `/profiles` | — | Liste des profils en base (id, profile_name, is_active, created_at, updated_at) — sans `raw_content` |
| POST | `/profiles` | multipart : `file` (Markdown/HTML en v1 ; PDF/DOCX à venir) + `profile_name?` | Upload d'un CV → **nouveau** `candidate_profile` (nouvel id). Contenu brut stocké dans `cv_raw_json.raw_content`. Devient actif si aucun profil actif n'existe. `201` + profil complet (avec `raw_content`) |
| PUT | `/profiles/{id}/activate` | — | Rend ce profil **actif** (désactive les autres). `200` + profil |
| PUT | `/profiles/{id}/deactivate` | — | Désactive le profil (`is_active = false`), sans toucher aux autres. Le **profil actif ne peut pas être désactivé** (`409`) : il faut d'abord activer un autre profil. `200` + profil, `404` si introuvable |
| PATCH | `/profiles/{id}` | `{profile_name}` (1–200 car., trimé) | Renomme le profil. `200` + profil, `404` si introuvable, `409` si le nom est déjà pris par un autre profil, `422` si vide |
| GET | `/profile` | — | Profil actif (`is_active = true`). `404` si aucun profil actif |
| GET | `/profile/{id}` | — | Profil par id (avec `raw_content` et `raw_content_markdown`) |

> Le détail du profil (`GET /profile`, `GET /profile/{id}`, réponses de `POST /profiles`,
> `PUT /.../activate`, `PUT /.../deactivate`, `PATCH /...`) expose le contenu brut du CV
> dans `raw_content` et sa conversion Markdown dans `raw_content_markdown` (un CV HTML
> est converti en Markdown côté serveur, un CV Markdown est renvoyé tel quel) — utilisé
> par le rendu « Aperçu » de l'interface. Les métadonnées du CV (`experience_years`,
> `location`, `preferred_contracts`) ne sont **plus extraites ni exposées**.

> **Matching et profils multiples** : le scoring est un **instantané au temps T**, contre le
> profil choisi. Un `match_result` n'est jamais recalculé a posteriori : si une offre
> intéresse le candidat, le CV est généré ; un score existant reste celui calculé à
> l'époque. Plusieurs profils coexistent (un par CV uploadé) ; le matching se fait contre
> n'importe lequel via `candidate_profile_id`. Relancer le matching sur un couple
> (offre, profil) déjà noté **écrase** le `match_result` existant (upsert sur
> `uq_match_unique_pair`) : l'interface propose « Relancer le matching » dès qu'un score
> existe, ce qui permet de re-scorer avec un autre profil sélectionné. Le matching est
> produit par le LLM Mistral (`mistral-small-latest`, clé `MISTRAL_API_KEY`) : sans clé ou
> en cas de réponse invalide, le matching renvoie `502`.
>
> **Anonymisation** : le LLM reçoit le **texte brut du CV, anonymisé** — nom, téléphone,
> email, code postal + ville et LinkedIn sont remplacés par des placeholders
> (`[NOM]`, `[EMAIL]`…) via `src/core/privacy/anonymize.py`. La version stockée du CV
> (`raw_content`) reste intégrale (affichage du profil et génération de CV).

## Offres

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| GET | `/job-offers` | `?limit=50&offset=0&company=&source=&archived=false&sort_by=ingested_at&order=desc` | Liste paginée `{total, limit, offset, items[]}`. On liste les annonces : pas de `candidate_profile_id`. Tri serveur sur `sort_by` (`title`, `company`, `location`, `source`, `ingested_at`) dans le sens `order` (`asc`/`desc`) ; défaut `ingested_at` décroissant. `archived` (bool, défaut `false`) restreint aux offres archivées (`true`) ou actives (`false`) ; chaque item expose `archived`. `company` (resp. `source`) filtre partiellement (insensible à la casse) sur le nom d'entreprise (resp. la source d'ingestion — ex. `hellowork`, nom de domaine de l'URL). Chaque item expose `source` (source d'ingestion) et `scores`, **tous** les scores de l'offre (tous profils) : `[{candidate_profile_id, profile_name, total_score, created_at, has_cv, has_letter, application_submitted}]`, du **meilleur score au plus faible** puis du **plus récent au plus ancien**. `has_cv` (resp. `has_letter`) indique qu'un CV généré (resp. une lettre de motivation) existe pour le couple — affiché comme indicateur **non cliquable** dans la cellule score (seul le score est cliquable). `application_submitted` : suivi « candidature envoyée » pour le couple (drapeau du `cv_version`) — affiché comme **coche verte** après les icônes CV/lettre dans la cellule score et dans le menu candidats du détail d'offre. Une offre est matchée dès qu'elle a **au moins un score** — il n'existe pas de statut « matchée / non matchée » séparé |
| GET | `/job-offers/{id}` | `?candidate_profile_id=` | Détail complet (profil ciblé ; défaut = actif) + `match_result` + CV du couple (au plus un, `cvs[]`) + lettre de motivation du couple (au plus une, `letters[]`). La réponse expose `candidate_profile_id` résolu, ainsi que `archived`, `archived_at` et `scores` (tous les scores de l'offre, source du menu candidats d'une offre archivée). `previous_offer_id` / `next_offer_id` : offres précédente/suivante dans la liste (`ingested_at DESC, id DESC`), restreintes au même ensemble archivé/actif ; `null` aux extrémités |
| PUT | `/job-offers/{id}/archived` | `{archived}` (bool) | Archive (`archived=true`) ou désarchive (`archived=false`) une offre → `{job_offer_id, archived, archived_at}`. `404` si l'offre est introuvable |
| POST | `/job-offers/from-url` | `{url, max_offers, source?}` — `max_offers` : int **1 → 20**, défaut **5** (nombre maximal d'offres **nouvelles** à ingérer pour une liste ; ignoré si `source` est fourni). `source` (optionnel) : contenu de la page collé (HTML du code source ou texte), **borné à 2 000 000 de caractères** (généreux car un code source embarque styles + JavaScript, retirés par la conversion) | Ingère une offre ou une liste d'offres depuis une URL : récupération de la page (Playwright), classification par le LLM (`mistral-small-latest`), puis pipeline d'ingestion existant (matching / CV / lettre immédiatement disponibles). **Offre unique** : le contenu est extrait par le LLM, dédoublonnage sur l'URL soumise. **Liste d'offres** : le LLM ne renvoie que les **URLs** ; celles déjà en base (colonne `url`, indépendamment de la source) sont **ignorées sans mise à jour** ; chacune des `max_offers` premières URLs **nouvelles** (ordre de la page) est récupérée individuellement (fetch Playwright + extraction mono-offre) et upsertée — un échec individuel est ignoré (`added` peut être < `max_offers`). **`source` fourni** : même ingestion mais **offre unique** — le contenu collé **remplace le fetch Playwright** (converti en texte : HTML → texte structuré, **`<script>`/`<style>`/`<noscript>`/`<svg>` retirés**, même conversion que le fetch, tronqué à 12 000 caractères) puis extrait par `extract_offer` (**mono-offre**), **sans récupérer l'URL** — elle est la clé de dédoublonnage (409 si déjà en base) et la source d'ingestion (domaine). Débloque les sites anti-bot (Indeed, APEC) **sans contournement automatisé** (c'est l'utilisateur qui colle le contenu). `201` + `{offers: JobOfferListItem[], added, already_present}` — `offers` : offres persistées dans l'ordre de la page, `added` : nouvelles insertions, `already_present` : nombre d'URLs de liste déjà en base (0 pour une offre unique — un doublon répond `409`). `409` **uniquement** si la page est une **offre unique** déjà en base (avec ou sans `source` ; une liste dont toutes les offres existent déjà renvoie `201` avec `added: 0`), `422` si l'URL est invalide (non-http(s)) ou si la page n'est pas une offre (avec `source` : un contenu collé de liste répond aussi 422 — les listes restent au fetch Playwright ; le message précise le motif quand le LLM l'identifie — ex. offre expirée), `413` si le `source` dépasse la borne (côté serveur, le texte soumis au LLM reste borné à 12 000 caractères), `502` si le LLM est indisponible |

> Le détail d'une offre accepte `?candidate_profile_id=` pour cibler un profil autre
> que l'actif (ex. vérifier le match d'un CV inactif). Absent → profil actif.
>
> **Offres archivées** : une offre archivée est **lecture seule** côté API — `POST /matching/run`,
> `DELETE /matching/{id}`, `POST /cvs/generate`, `POST /letters/generate` et
> `DELETE /job-offers/{id}/cv` / `DELETE /job-offers/{id}/letter` renvoient `409` sur une offre
> archivée.

## Matching

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| POST | `/matching/run` | `{job_offer_id, candidate_profile_id?}` | Matching **LLM** (mistral-small-latest) sur le **CV brut anonymisé** → match complet (score, breakdown, forces, faiblesses, compétences manquantes, explication personnalisée pour ajuster la candidature). `score_breakdown` = `{title_score, skills_score, experience_score, education_score}` (0-1). `502` si le LLM est indisponible |
| DELETE | `/matching/{job_offer_id}` | `?candidate_profile_id=` | Supprime le matching d'un couple (offre, profil) **et ses CV et lettres associés** : l'offre redevient vierge pour ce profil (plus de score, plus de CV, plus de lettre). `204`. `404` si l'offre est introuvable ou si aucun matching n'existe pour le couple ; `409` si l'offre est archivée |

## CV

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| POST | `/cvs/generate` | `{job_offer_id, candidate_profile_id?}` | `{cv_id, score}` (`409` si pas de match, `502` si le LLM est indisponible). **Un seul CV par couple** : une génération existante est remplacée (upsert), sans notion de version |
| DELETE | `/job-offers/{id}/cv` | `?candidate_profile_id=` | Supprime le CV généré du couple (offre, profil) — **le matching est conservé**. `204`. `404` si aucun CV pour le couple ; `409` si l'offre est archivée |
| GET | `/cvs/{id}` | — | Détail d'un CV : `cv_text` (**Markdown généré** par le LLM, rendu front via react-markdown), `tailoring_notes` (désormais toujours vide), `application_submitted`, métadonnées |
| GET | `/cvs/{id}/pdf` | — | **PDF téléchargeable** du CV généré (Markdown converti côté serveur, texte sélectionnable). `Content-Disposition: attachment` → fichier `cv_{id}.pdf`. `404` si le CV est introuvable |
| PUT | `/cvs/{id}/submitted` | `{submitted}` — bool | Bascule le suivi « candidature envoyée » du CV (état voulu, **idempotent**). Retour `CVSummary`. `404` si le CV est introuvable. Autorisé sur une offre archivée (drapeau de suivi, pas une mutation de document) |

> **Suivi « candidature envoyée »** : `application_submitted` (bool, défaut `false`)
> est porté par chaque `cv_version` — donc par `cvs[]` du détail d'offre, par le
> détail d'un CV et par chaque score item (`scores[]` de la liste et du détail
> d'offre, `application_submitted`). C'est un suivi utilisateur par couple (offre,
> profil) : une fois la candidature déposée pour une offre avec un profil,
> l'interface remplace le bouton « Candidature envoyée » par un badge vert
> cliquable et affiche une **coche verte** dans la cellule score de la liste des
> offres et dans le menu candidats du détail d'offre. Revertible au re-clic.
> Le drapeau est **préservé** à la régénération du CV (upsert du couple) ; il
> revient à `false` si le CV est supprimé puis regénéré.

> **Source des profils** : les profils sont **uploadés via l'interface** (un CV → un
> `candidate_profile`, nouvel id). Le contenu brut est stocké dans
> `cv_raw_json.raw_content`. La génération fait **recomposer** par le LLM le **CV brut anonymisé**
> pour l'offre choisie : mêmes rubriques (`##`/`###`) et mise en forme, points forts mis en
> avant, sans rien inventer. Les coordonnées réelles (nom, email, téléphone, LinkedIn) ne
> sont **jamais transmises au LLM** : elles sont réinjectées par le serveur dans un en-tête
> après génération. `cv_content_json` = `{"markdown": …}`.
>
> **Génération en une passe** (`humanize_cv_markdown`) : la pass 1 **recompose**
> le CV — **Recomposition ciblée** : réorganiser, condenser et reformuler
> légèrement les informations **déjà présentes** dans le CV socle pour mettre en
> avant celles les plus pertinentes pour l'offre, sans modifier les faits, le
> niveau de preuve, l'identité professionnelle, les responsabilités ou le niveau
> d'expertise du candidat — avec **fidélité factuelle stricte** : le CV original
> anonymisé est l'unique source de vérité, aucune invention de compétence, de
> chiffre, de résultat ou de niveau de responsabilité (anti-bullshit ATS).
> **Portée de la recomposition** : conserver toutes les expériences et toutes
> les informations factuelles du CV socle (aucune expérience supprimée) ; la
> recomposition porte principalement sur titre, résumé professionnel, ordre des
> compétences, ordre des projets, formulation de certaines réalisations,
> visibilité relative des technologies. La pass 2
> (réécriture « humaine » sur `HUMANIZE_LLM`,
> **`mistral-large-latest`**) est **désactivée** : ses prompts et son code sont
> conservés pour un usage futur mais **jamais appelés**. La pass 1 exige le LLM :
> `502` si la clé est absente ou l'API en erreur (pas de fallback).

## Lettres de motivation

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| POST | `/letters/generate` | `{job_offer_id, candidate_profile_id?}` | `{letter_id, score}` (`score` = total du match du couple). `409` si pas de match, `502` si le LLM est indisponible. **Une seule lettre par couple** : une génération existante est remplacée (upsert), sans notion de version |
| DELETE | `/job-offers/{id}/letter` | `?candidate_profile_id=` | Supprime la lettre générée du couple (offre, profil) — **le matching et le CV sont conservés**. `204`. `404` si aucune lettre pour le couple ; `409` si l'offre est archivée |
| GET | `/letters/{id}` | — | Détail d'une lettre : `letter_text` (**Markdown généré** par le LLM, rendu front via react-markdown), métadonnées |

> **Source candidat** : la lettre est rédigée à partir de l'offre et du CV du couple — le
> **CV généré** (`cv_version.cv_text`) s'il existe, sinon le **CV brut du profil**
> (`cv_raw_json.raw_content`). Le contenu envoyé au LLM est **anonymisé** (nom, email,
> téléphone, code postal + ville, LinkedIn remplacés par des placeholders) et la lettre
> générée **reste anonyme** : aucune coordonnée n'est réinjectée côté serveur, elle se
> termine par la formule de politesse (un nettoyage `clean_letter_markdown` retire les
> placeholders résiduels). `letter_content_json` = `{"markdown": …}`. Pas de PDF : la lettre
> est destinée à être **copiée** et collée dans un document ou un email (bouton « Copier » du front).
>
> **Génération en deux passes** (`humanize_letter_markdown`) : la pass 1 rédige la lettre
> (comportement historique, inchangé) ; la pass 2, **best-effort**, la réécrit
> systématiquement avec un style humain
> (structure variée, détails personnels tirés du CV, adjectifs vagues remplacés par des
> faits, touche émotionnelle, fin naturelle). La pass 2 utilise la même instance dédiée que
> la génération de CV (`HUMANIZE_LLM`, **`mistral-large-latest`**), indépendante du modèle
> de génération. En cas d'échec de la
> pass 2 (réécriture), la lettre de la pass 1 est conservée — la lettre reste
> anonyme dans tous les cas. La pass 1 exige le LLM : `502` si la clé est absente ou
> l'API en erreur.

## Paramètres de recherche

| Méthode | Endpoint | Corps / params | Retour |
|---|---|---|---|
| GET | `/search-parameters` | — | Liste des paramètres (id, title, source, url, max_offers, is_active, created_at, updated_at), du plus récent au plus ancien |
| POST | `/search-parameters` | `{title, source, url, max_offers}` (trimés ; URL `http`/`https` obligatoire) | `201` + paramètre. `409` si l'URL existe déjà, `422` si l'URL n'est pas `http(s)`, si un champ est vide ou si `max_offers` est hors bornes |
| PATCH | `/search-parameters/{id}` | `{title, source, url, max_offers}` (les quatre requis) | `200` + paramètre. `404` si introuvable, `409` si l'URL est déjà utilisée par un autre paramètre, `422` si un champ est vide, l'URL non `http(s)` ou `max_offers` hors bornes |
| DELETE | `/search-parameters/{id}` | — | `204`. `404` si introuvable |
| PUT | `/search-parameters/{id}/activate` | — | `200` + paramètre (`is_active` vrai). `404` si introuvable |
| PUT | `/search-parameters/{id}/deactivate` | — | `200` + paramètre (`is_active` faux). `404` si introuvable |
| POST | `/search-parameters/run` | — | `200` + résumé de l'ingestion (voir ci-dessous). Exécute l'agent de recherche immédiatement — même pipeline que le DAG `search_parameters_agent` (lecture des paramètres puis ingestion des offres de chaque URL **active**, matching/CV/lettre à la demande). Synchrone : la réponse n'arrive qu'en fin de run. Un paramètre en échec n'interrompt pas le run |
| POST | `/search-parameters/{id}/run` | — | `200` + résumé de l'ingestion pour **une** recherche (lancement unitaire par ligne). Même pipeline que `/run` mais pour un seul paramètre, **qu'il soit actif ou non** (test ponctuel, `is_active` inchangé). `404` si l'id est inconnu |

> **URL unique** : la contrainte `uq_search_parameters_url` dédoublonne sur l'URL exacte
> (sensible à la casse). La validation `http`/`https` est faite par le schéma Pydantic
> (`str` simple, pas `HttpUrl`) pour garder la maîtrise du message d'erreur `422`.
>
> **`max_offers`** : entier **1 → 20**, défaut **5** (validé par Pydantic `ge=1, le=20` et,
> en base, par la contrainte `chk_search_parameters_max_offers`). C'est le nombre
> maximal d'offres récupérées par l'agent de recherche (DAG `search_parameters_agent`)
> pour ce paramètre : pour une liste, seules les offres **nouvelles** (non déjà en base)
> sont ajoutées, jusqu'à `max_offers`, dans l'ordre de la page.
>
> **`POST /search-parameters/run`** : appelle `SearchParametersAgentService().run()`
> (le service que le DAG exécute), sans passer par l'API REST d'Airflow. La réponse est le
> résumé JSON-sérialisable `{total, succeeded, duplicates, scraping_failed, llm_failed,
> other_failed, added_offers, already_present, parameters[]}` — chaque `parameters[]` est
> `{id, title, source, url, max_offers, status, added?, already_present?}` avec `status` ∈
> `ok | duplicate | scraping_failed | llm_failed | error`. Côté UI, le bouton « Exécuter »
> de la page Recherches sauvegardées déclenche cet endpoint et affiche le résumé.
>
> **`POST /search-parameters/{id}/run`** : appelle `SearchParametersAgentService
> .run_parameter_by_id(id)` (la logique d'une entrée du résumé, partagée avec `run()`).
> Résumé identique (total = 1) ; le triangle par ligne de l'UI déclenche cet endpoint et
> affiche une bannière enrichie du **titre** et de la **source** de la recherche.
>
> **`is_active`** : un paramètre est **actif** à la création (`TRUE`, défaut base). Seuls
> les paramètres **actifs** sont pris en compte par l'agent de recherche (DAG et bouton
> Exécuter) — les inactifs sont ignorés sans erreur. **Exception** : le lancement unitaire
> (`/search-parameters/{id}/run`) exécute la recherche demandée même si elle est inactive —
> c'est un test ponctuel, il ne modifie pas `is_active`. La bascule se fait via les
> endpoints `PUT /search-parameters/{id}/activate` et `/deactivate` (colonne « Statut » +
> toggle du tableau). Un paramètre inactif reste listé, modifiable et supprimable.

## Stats & santé

| Méthode | Endpoint | Retour |
|---|---|---|
| GET | `/stats` | `{profile_loaded, offers_total, offers_with_cv, cvs_generated, last_ingested_at}`. `offers_with_cv` est **global** (tous profils confondus) : une offre est comptée dès qu'elle a ≥1 CV |
| GET | `/healthz` | Liveness (sans DB) |
| GET | `/readyz` | Vérifie la connexion DB |

## État d'implémentation (build API)

Les requêtes de lecture et modifications ci-dessous ont été **implémentées** avec la
création de l'API :

### Repositories ajoutés
- `job_offer_repository.list_offers(...)` — pagination + filtres (`company`, `archived`) + tri serveur whitelisté (`sort_by`/`order`, défaut `ingested_at` desc) + chargement de **tous** les scores par offre (nom de profil inclus), triés par score puis date décroissants. Il n'existe pas de statut « matchée / non matchée » : une offre est matchée dès qu'elle a au moins un score.
- `job_offer_repository.set_archived(...)` — archive / désarchive (`archived` + `archived_at`) ; `scores_for_offer(...)` — tous les scores d'une offre (détail) ; `neighbors(...)` — offres précédente/suivante d'une offre (détail).
- `match_result_repository.delete_for_pair(...)` — supprime le matching d'un couple (offre, profil) **et ses CV et lettres associés** (base du `DELETE /matching/{id}`).
- `cv_version_repository.get_by_id(...)` et `list_for_offer(...)`.
- `letter_version_repository.get_by_id(...)`, `list_for_offer(...)`, `upsert(...)` (une lettre par couple) et `delete_for_pair(...)`.
- `candidate_profile_repository.insert(...)`, `list_all(...)`, `get_active()`, `set_active(..., active=True|False)`, `rename(...)`.
- `search_parameters_repository.list_all(...)`, `get_by_url(...)`, `get_by_id(...)`, `insert(...)`, `update(...)`, `delete(...)` — table `search_parameters` (CRUD `/search-parameters`, URL unique `uq_search_parameters_url`, lecture d'une ligne pour le run unitaire).
- `stats_repository.get_stats(...)` — comptages `/stats`.

### Modifications apportées
- `ProfileParserService.run_from_content(...)` : entrée **contenu uploadé** ; l'ancien flux
  fichier et ses constantes de configuration ont été supprimés.
- Schéma : colonne `is_active` + index unique partiel `uq_candidate_profile_active` (un seul profil actif) ; colonnes `archived` / `archived_at` sur `job_offer` ; table `letter_version` (une lettre par couple, `uq_letter_version_pair`) (migration idempotente via `ensure_schema`).
- `bootstrap.ensure_schema` : exécution en autocommit par instruction (`CREATE INDEX CONCURRENTLY`
  est interdit en transaction — `engine.begin()` échouait sur base fraîche). L'API l'applique
  au démarrage via son `lifespan` (idempotent) : plus de migration manuelle après un changement
  de `sql/tables.sql` sur la base de dev.

## Structure de l'API (esquisse)

```
api/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py          # create_app, CORS, montage des routers
    ├── dependencies.py  # résolution du profil actif (is_active), session DB
    ├── schemas/         # Pydantic : profile.py, job_offer.py, match.py, cv.py, letter.py
    └── routers/         # profile.py, job_offers.py, matching.py, cvs.py, letters.py, stats.py
```

Le service FastAPI importe `src.services.*` et `src.infrastructure.db.*` (même dépôt,
`PYTHONPATH` sur la racine, volumes `src/`, `sql/`, `data/`, variable `DATABASE_URL`),
comme le fait Airflow.
