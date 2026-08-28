"""Routes du tableau de bord."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.app.dependencies import get_db
from src.infrastructure.db.repositories import (
    candidate_profile_repository,
    stats_repository,
)

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Comptages pour le tableau de bord."""
    active = candidate_profile_repository.get_active(db)
    stats = stats_repository.get_stats(db)
    return {
        "profile_loaded": active is not None,
        "profile_id": active.id if active is not None else None,
        **stats,
    }
