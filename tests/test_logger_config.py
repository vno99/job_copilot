"""Tests de ``config.logger_config``.

Le point clé : sous Airflow, ``setup_logging`` ne doit pas reconfigurer le
logging (``dictConfig``) — sinon il écrase la config d'Airflow et le handler
console (stderr) fait apparaître les INFO comme des ERROR dans les logs de
tâche.
"""

import logging
import sys

import pytest

from config.logger_config import setup_logging


@pytest.fixture()
def _restore_root_handlers():
    """Sauvegarde et restaure les handlers du logger racine."""
    root = logging.getLogger()
    original = list(root.handlers)
    yield
    root.handlers.clear()
    for handler in original:
        root.addHandler(handler)


def test_setup_logging_skips_reconfig_under_airflow(monkeypatch, _restore_root_handlers):
    """Sous Airflow (module ``airflow`` importé), la racine n'est pas touchée."""
    class FakeAirflow:
        pass

    monkeypatch.setitem(sys.modules, "airflow", FakeAirflow())

    root = logging.getLogger()
    preexisting = set(root.handlers)

    logger = setup_logging("test.airflow.module")

    assert set(root.handlers) == preexisting
    assert logger.name == "test.airflow.module"


def test_setup_logging_installs_handlers_locally(monkeypatch, tmp_path, _restore_root_handlers):
    """Hors Airflow, la config ``logging.yml`` installe console + file."""
    monkeypatch.delitem(sys.modules, "airflow", raising=False)

    logger = setup_logging("test.local.module", log_dir=str(tmp_path))

    assert logger.name == "test.local.module"
    handler_types = {type(h).__name__ for h in logging.getLogger().handlers}
    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" in handler_types
    # Le fichier de log est bien créé dans le dossier demandé.
    assert (tmp_path / "app.log").exists()
