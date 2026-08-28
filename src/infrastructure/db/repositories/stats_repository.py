"""Comptages pour le tableau de bord (endpoint ``/stats``)."""

from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.infrastructure.db.models.cv_version import CVVersionModel
from src.infrastructure.db.models.job_offer import JobOfferModel


def get_stats(session: Session) -> Dict[str, Any]:
    """Comptages globaux (tous profils confondus).

    ``offers_with_cv`` compte les offres ayant **au moins un** CV (un seul par couple),
    indépendant du profil actif.

    Returns:
        Dict avec : offers_total, offers_with_cv, cvs_generated,
        last_ingested_at.
    """
    offers_total = session.execute(
        select(func.count(JobOfferModel.id))
    ).scalar_one()
    last_ingested_at = session.execute(
        select(func.max(JobOfferModel.ingested_at))
    ).scalar()
    cvs_generated = session.execute(
        select(func.count(CVVersionModel.id))
    ).scalar_one()

    offers_with_cv = session.execute(
        select(func.count(func.distinct(CVVersionModel.job_offer_id)))
    ).scalar_one()

    return {
        "offers_total": offers_total,
        "offers_with_cv": offers_with_cv,
        "cvs_generated": cvs_generated,
        "last_ingested_at": last_ingested_at,
    }
