"""Accès à la table ``letter_version``.

Une seule lettre par couple (offre, profil) : la génération remplace l'existant
via ``upsert`` (contrainte ``uq_letter_version_pair``).
"""

from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.infrastructure.db.models.letter_version import LetterVersionModel


def get_by_id(
    session: Session, letter_id: int
) -> Optional[LetterVersionModel]:
    """Une lettre générée par son id."""
    return session.get(LetterVersionModel, letter_id)


def list_for_offer(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> List[LetterVersionModel]:
    """Lettres d'un couple (offre, profil), de la plus récente à la plus ancienne (0 ou 1)."""
    stmt = (
        select(LetterVersionModel)
        .where(
            LetterVersionModel.job_offer_id == job_offer_id,
            LetterVersionModel.candidate_profile_id == candidate_profile_id,
        )
        .order_by(LetterVersionModel.id.desc())
    )
    return list(session.scalars(stmt))


def upsert(session: Session, record: Dict) -> int:
    """Insère ou remplace la lettre d'un couple sur ``uq_letter_version_pair``.

    Returns:
        L'id de la ligne (insérée ou mise à jour).
    """
    stmt = (
        pg_insert(LetterVersionModel)
        .values(record)
        .on_conflict_do_update(
            constraint="uq_letter_version_pair",
            set_={
                k: v
                for k, v in record.items()
                if k not in ("job_offer_id", "candidate_profile_id")
            },
        )
        .returning(LetterVersionModel.id)
    )
    return session.execute(stmt).scalar_one()


def delete_for_pair(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> bool:
    """Supprime la/les lettre(s) d'un couple (offre, profil).

    Returns:
        True si au moins une ligne a été supprimée, False sinon.
    """
    result = session.execute(
        delete(LetterVersionModel).where(
            LetterVersionModel.job_offer_id == job_offer_id,
            LetterVersionModel.candidate_profile_id == candidate_profile_id,
        )
    )
    return result.rowcount > 0
