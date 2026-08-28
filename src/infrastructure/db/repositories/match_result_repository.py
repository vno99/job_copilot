"""Accès à la table ``match_result``."""

from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.infrastructure.db.models.cv_version import CVVersionModel
from src.infrastructure.db.models.letter_version import LetterVersionModel
from src.infrastructure.db.models.match_result import MatchResultModel


def exists(session: Session, job_offer_id: int, candidate_profile_id: int) -> bool:
    stmt = select(MatchResultModel.id).where(
        MatchResultModel.job_offer_id == job_offer_id,
        MatchResultModel.candidate_profile_id == candidate_profile_id,
    )
    return session.execute(stmt).first() is not None


def get_by_pair(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> Optional[MatchResultModel]:
    stmt = select(MatchResultModel).where(
        MatchResultModel.job_offer_id == job_offer_id,
        MatchResultModel.candidate_profile_id == candidate_profile_id,
    )
    return session.scalars(stmt).first()


def delete_for_pair(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> bool:
    """Supprime le matching d'un couple (offre, profil) et ses CV et lettres associés.

    L'offre redevient vierge pour ce profil (plus de score, plus de CV, plus de
    lettre de motivation). Les ``cv_version`` et ``letter_version`` sont
    supprimées avant le ``match_result`` pour éviter le ``ON DELETE SET NULL``
    de la FK ``match_result_id``.

    Returns:
        True si un ``match_result`` existait pour ce couple (et a donc été
        supprimé), False sinon.
    """
    if not exists(session, job_offer_id, candidate_profile_id):
        return False
    session.execute(
        delete(CVVersionModel).where(
            CVVersionModel.job_offer_id == job_offer_id,
            CVVersionModel.candidate_profile_id == candidate_profile_id,
        )
    )
    session.execute(
        delete(LetterVersionModel).where(
            LetterVersionModel.job_offer_id == job_offer_id,
            LetterVersionModel.candidate_profile_id == candidate_profile_id,
        )
    )
    session.execute(
        delete(MatchResultModel).where(
            MatchResultModel.job_offer_id == job_offer_id,
            MatchResultModel.candidate_profile_id == candidate_profile_id,
        )
    )
    return True


def upsert(session: Session, record: Dict) -> int:
    """Insère ou met à jour sur UNIQUE(job_offer_id, candidate_profile_id).

    Returns:
        L'id du résultat (inséré ou existant).
    """
    stmt = (
        pg_insert(MatchResultModel)
        .values(record)
        .on_conflict_do_update(
            constraint="uq_match_unique_pair",
            set_={
                k: v
                for k, v in record.items()
                if k not in ("job_offer_id", "candidate_profile_id")
            },
        )
        .returning(MatchResultModel.id)
    )
    return session.execute(stmt).scalar_one()


def list_unmatched_cv(
    session: Session, candidate_profile_id: int, limit: Optional[int] = None
) -> List[MatchResultModel]:
    """Résultats de matching n'ayant pas encore de ``cv_version`` pour ce profil."""
    stmt = (
        select(MatchResultModel)
        .outerjoin(
            CVVersionModel,
            CVVersionModel.match_result_id == MatchResultModel.id,
        )
        .where(
            MatchResultModel.candidate_profile_id == candidate_profile_id,
            CVVersionModel.id.is_(None),
        )
        .order_by(MatchResultModel.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))
