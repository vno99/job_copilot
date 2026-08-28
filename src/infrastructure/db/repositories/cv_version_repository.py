"""Accès à la table ``cv_version``.

Un seul CV par couple (offre, profil) : la génération remplace l'existant via
``upsert`` (contrainte ``uq_cv_version_pair``).
"""

from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.infrastructure.db.models.cv_version import CVVersionModel


def get_by_id(session: Session, cv_id: int) -> Optional[CVVersionModel]:
    """Un CV généré par son id."""
    return session.get(CVVersionModel, cv_id)


def set_application_submitted(
    session: Session, cv_id: int, submitted: bool
) -> Optional[CVVersionModel]:
    """Bascule le drapeau « candidature envoyée » d'un CV et retourne la ligne.

    ``submitted`` est l'état voulu (idempotent : envoyer la même valeur deux
    fois n'a pas d'effet). Retourne ``None`` si le CV n'existe pas.
    """
    row = session.get(CVVersionModel, cv_id)
    if row is None:
        return None
    row.application_submitted = submitted
    session.flush()
    return row


def list_for_offer(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> List[CVVersionModel]:
    """CV d'un couple (offre, profil), du plus récent au plus ancien (0 ou 1)."""
    stmt = (
        select(CVVersionModel)
        .where(
            CVVersionModel.job_offer_id == job_offer_id,
            CVVersionModel.candidate_profile_id == candidate_profile_id,
        )
        .order_by(CVVersionModel.id.desc())
    )
    return list(session.scalars(stmt))


def upsert(session: Session, record: Dict) -> int:
    """Insère ou remplace le CV d'un couple sur ``uq_cv_version_pair``.

    Returns:
        L'id de la ligne (insérée ou mise à jour).
    """
    stmt = (
        pg_insert(CVVersionModel)
        .values(record)
        .on_conflict_do_update(
            constraint="uq_cv_version_pair",
            set_={
                k: v
                for k, v in record.items()
                if k not in ("job_offer_id", "candidate_profile_id")
            },
        )
        .returning(CVVersionModel.id)
    )
    return session.execute(stmt).scalar_one()


def delete_for_pair(
    session: Session, job_offer_id: int, candidate_profile_id: int
) -> bool:
    """Supprime le(s) CV d'un couple (offre, profil).

    Returns:
        True si au moins une ligne a été supprimée, False sinon.
    """
    result = session.execute(
        delete(CVVersionModel).where(
            CVVersionModel.job_offer_id == job_offer_id,
            CVVersionModel.candidate_profile_id == candidate_profile_id,
        )
    )
    return result.rowcount > 0
