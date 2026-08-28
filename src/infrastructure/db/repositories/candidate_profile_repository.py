"""Accès à la table ``candidate_profile``."""

from typing import Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.infrastructure.db.models.candidate_profile import CandidateProfileModel


def get_by_name(
    session: Session, profile_name: str
) -> Optional[CandidateProfileModel]:
    stmt = select(CandidateProfileModel).where(
        CandidateProfileModel.profile_name == profile_name
    )
    return session.scalars(stmt).first()


def upsert(session: Session, profile: Dict) -> int:
    """Insère ou met à jour un profil sur UNIQUE(profile_name).

    Returns:
        L'id du profil (inséré ou existant).
    """
    stmt = (
        pg_insert(CandidateProfileModel)
        .values(profile)
        .on_conflict_do_update(
            constraint="uq_candidate_profile_name",
            set_={
                k: v for k, v in profile.items() if k != "profile_name"
            }
            | {"updated_at": func.now()},
        )
        .returning(CandidateProfileModel.id)
    )
    return session.execute(stmt).scalar_one()


def insert(session: Session, profile: Dict) -> int:
    """Insère un nouveau profil (upload de CV) et renvoie son id.

    Contrairement à ``upsert``, crée toujours une nouvelle ligne : un CV uploadé
    devient un ``candidate_profile`` distinct avec un nouvel id.
    """
    row = CandidateProfileModel(**profile)
    session.add(row)
    session.flush()
    return row.id


def list_all(session: Session) -> List[CandidateProfileModel]:
    """Tous les profils, du plus récent au plus ancien."""
    stmt = select(CandidateProfileModel).order_by(CandidateProfileModel.id.desc())
    return list(session.scalars(stmt))


def get_active(session: Session) -> Optional[CandidateProfileModel]:
    """Le profil actif (``is_active`` vrai), s'il existe."""
    stmt = select(CandidateProfileModel).where(
        CandidateProfileModel.is_active.is_(True)
    )
    return session.scalars(stmt).first()


def set_active(
    session: Session, profile_id: int, active: bool = True
) -> bool:
    """Active ou désactive le profil ``profile_id``.

    Avec ``active=True`` (défaut), désactive d'abord tous les autres profils
    (un seul actif garanti). Avec ``active=False``, met uniquement ``is_active``
    à false, sans toucher aux autres.

    Returns:
        True si le profil existe, False sinon.
    """
    target = session.get(CandidateProfileModel, profile_id)
    if target is None:
        return False
    if active:
        session.execute(
            update(CandidateProfileModel)
            .where(CandidateProfileModel.is_active.is_(True))
            .values(is_active=False)
        )
    target.is_active = active
    return True


def rename(
    session: Session, profile_id: int, name: str
) -> Optional[CandidateProfileModel]:
    """Renomme un profil et le retourne (None si absent)."""
    row = session.get(CandidateProfileModel, profile_id)
    if row is None:
        return None
    row.profile_name = name
    return row
