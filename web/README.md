# web — Interface job_copilot

Interface Next.js (App Router, Tailwind CSS v4, TanStack Query v5) de validation des
offres et de recomposition de CV : consultation des offres scrapées (actives / archivées),
matching offre × profil par LLM, génération de CV recomposé et de lettre de motivation.

L'architecture complète (scraping Airflow, API FastAPI, base PostgreSQL) est décrite
dans le [`../README.md`](../README.md) et le `CLAUDE.md` du dépôt racine.

## Prérequis

- Node.js ≥ 20 (`node --version`), npm.
- La base applicative et l'API FastAPI : depuis la racine, `docker compose up -d postgres-data api`
  ou `npm run dev` en local avec l'API servie sur `http://localhost:8000`.

## Commandes

```bash
npm install          # installe les dépendances
npm run dev          # serveur de dev (http://localhost:3000)
npm test             # tests unitaires (vitest, exécution unique)
npm run test:watch   # tests unitaires en mode watch
npm run lint         # ESLint
npm run build        # build de production (sortie "standalone")
```

## Proxying vers l'API

Le navigateur ne parle qu'à Next.js : les requêtes `/api/v1/*` sont proxifiées côté
serveur vers l'API FastAPI (`next.config.ts`, variable d'environnement `API_URL`,
défaut `http://localhost:8000`). Le contrat complet de l'API vit dans
[`../docs/api-contract.md`](../docs/api-contract.md).

## Tests

Vitest + Testing Library (config `vitest.config.mts`, setup `src/test/setup.ts`), tests
colocalisés sous `src/**/__tests__/`. `next/link` et `next/navigation` sont mockés dans
les tests de composants.
