"""Dépendances FastAPI : session DB et résolution du profil actif."""

from typing import Iterator, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.repositories import candidate_profile_repository
from src.infrastructure.db.session import SessionLocal


def get_db() -> Iterator[Session]:
    """Session SQLAlchemy avec commit/rollback automatique."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def active_profile_id(db: Session) -> int:
    """Id du profil actif, ou 404 si aucun profil n'est actif."""
    active = candidate_profile_repository.get_active(db)
    if active is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun profil actif : uploadez un CV (POST /api/v1/profiles)",
        )
    return active.id


def active_profile_id_or_none(db: Session) -> Optional[int]:
    """Id du profil actif, ou None s'il n'en existe pas."""
    active = candidate_profile_repository.get_active(db)
    return active.id if active is not None else None


def resolve_profile_id(db: Session, requested: Optional[int]) -> int:
    """Id du profil demandé, ou du profil actif si aucun n'est fourni."""
    if requested is not None:
        return requested
    return active_profile_id(db)


def ensure_not_archived(db: Session, job_offer_id: int) -> None:
    """Vérifie qu'une offre existe et n'est pas archivée (409 sinon).

    Appelée avant les actions matching / sélection / génération de CV : une
    offre archivée est en lecture seule.
    """
    job = db.get(JobOfferModel, job_offer_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Offre {job_offer_id} introuvable"
        )
    if job.archived:
        raise HTTPException(
            status_code=409,
            detail="Offre archivée : les actions matching / sélection / CV sont désactivées",
        )
