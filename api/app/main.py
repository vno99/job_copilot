"""Point d'entrée de l'API FastAPI job_copilot.

Lancement (depuis la racine du projet) :
    uvicorn api.app.main:app --reload

Au démarrage, le schéma applicatif est appliqué (``ensure_schema``, idempotent)
pour que la base de dev soit toujours à jour avec ``sql/tables.sql`` : plus de
migration manuelle après un changement de schéma.
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.app.dependencies import get_db
from api.app.routers import (
    cvs,
    job_offers,
    letters,
    matching,
    profile,
    search_parameters,
    stats,
)
from config.logger_config import setup_logging
from src.infrastructure.db.bootstrap import ensure_schema
from src.infrastructure.db.session import get_engine

logger = setup_logging(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Applique le schéma applicatif au démarrage (``ensure_schema``, idempotent).

    ``sql/tables.sql`` est la source de vérité : l'exécuter à chaque démarrage
    garantit que la base de dev est à jour après un ``git pull`` ou une
    modification locale du schéma. L'API ne bloque pas son démarrage si la base
    est injoignable : l'erreur est journalisée et les endpoints échoueront avec
    un 500 tant que la cause n'est pas résolue (pas de crash loop).
    """
    try:
        ensure_schema(get_engine())
    except Exception:
        logger.exception(
            "Échec de l'application du schéma applicatif au démarrage "
            "(ensure_schema) : vérifiez la base postgres-data"
        )
    yield


app = FastAPI(
    title="job_copilot API",
    description=(
        "Interface de validation : offres, matching, sélection et génération "
        "de CV recomposés."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router, prefix=API_PREFIX)
app.include_router(job_offers.router, prefix=API_PREFIX)
app.include_router(matching.router, prefix=API_PREFIX)
app.include_router(cvs.router, prefix=API_PREFIX)
app.include_router(letters.router, prefix=API_PREFIX)
app.include_router(search_parameters.router, prefix=API_PREFIX)
app.include_router(stats.router, prefix=API_PREFIX)


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz(db=Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
