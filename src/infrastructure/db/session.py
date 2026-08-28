"""Création de l'engine et gestion de sessions SQLAlchemy."""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import DATABASE_URL

engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_engine() -> Engine:
    """Retourne l'engine courant (module-level)."""
    return engine


def configure_database(url: str) -> None:
    """Re-pointe l'engine (et SessionLocal) vers une autre base.

    Utilisé par les tests d'intégration (conteneur PostgreSQL jetable) :
    dispose l'engine existant puis le remplace par un engine sur ``url``.
    ``SessionLocal`` est ré-affecté via ``.configure()`` ; comme ``get_db`` et
    ``session_scope`` instancient les sessions au moment de l'appel, le rebind
    est capté à l'exécution, en prod comme en test.
    """
    global engine
    engine.dispose()
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal.configure(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Fournit une session avec commit/rollback automatique.

    Commit si aucune exception, rollback sinon, fermeture systématique.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
