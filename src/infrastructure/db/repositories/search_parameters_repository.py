"""Accès à la table ``search_parameters``."""

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.db.models.search_parameters import SearchParameterModel


def list_all(session: Session) -> List[SearchParameterModel]:
    """Tous les paramètres de recherche, du plus récent au plus ancien."""
    stmt = select(SearchParameterModel).order_by(SearchParameterModel.id.desc())
    return list(session.scalars(stmt))


def get_by_url(
    session: Session, url: str
) -> Optional[SearchParameterModel]:
    """Le paramètre dont l'URL est ``url``, s'il existe (dédoublonnage)."""
    stmt = select(SearchParameterModel).where(
        SearchParameterModel.url == url
    )
    return session.scalars(stmt).first()


def get_by_id(session: Session, param_id: int) -> Optional[SearchParameterModel]:
    """Le paramètre d'id ``param_id``, s'il existe (exécution unitaire)."""
    return session.get(SearchParameterModel, param_id)


def insert(session: Session, data: Dict) -> int:
    """Insère un nouveau paramètre de recherche et renvoie son id."""
    row = SearchParameterModel(**data)
    session.add(row)
    session.flush()
    return row.id


def update(
    session: Session, param_id: int, data: Dict
) -> Optional[SearchParameterModel]:
    """Met à jour un paramètre et le retourne (None si absent)."""
    row = session.get(SearchParameterModel, param_id)
    if row is None:
        return None
    row.title = data["title"]
    row.source = data["source"]
    row.url = data["url"]
    row.max_offers = data["max_offers"]
    return row


def set_active(
    session: Session, param_id: int, active: bool = True
) -> bool:
    """Active ou désactive un paramètre. True si la ligne existait."""
    row = session.get(SearchParameterModel, param_id)
    if row is None:
        return False
    row.is_active = active
    return True


def delete(session: Session, param_id: int) -> bool:
    """Supprime un paramètre. True si la ligne existait, False sinon."""
    row = session.get(SearchParameterModel, param_id)
    if row is None:
        return False
    session.delete(row)
    return True
