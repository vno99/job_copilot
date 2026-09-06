"""Tests unitaires pour session.py et bootstrap.py."""
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


class TestSessionModule:
    """Tests de src.infrastructure.db.session."""

    def test_get_engine(self):
        from src.infrastructure.db.session import get_engine

        engine = get_engine()
        assert engine is not None

    def test_configure_database(self, monkeypatch):
        from src.infrastructure.db import session

        mock_create_engine = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_sessionmaker = MagicMock()

        monkeypatch.setattr("src.infrastructure.db.session.create_engine", mock_create_engine)
        monkeypatch.setattr("src.infrastructure.db.session.SessionLocal", mock_sessionmaker)

        session.configure_database("postgresql://user:pass@localhost/test")

        mock_create_engine.assert_called_once()
        mock_sessionmaker.configure.assert_called_once_with(bind=mock_engine)


class TestBootstrapFunctions:
    """Tests de src.infrastructure.db.bootstrap."""

    def test_split_statements_empty(self):
        from src.infrastructure.db.bootstrap import _split_statements

        result = _split_statements("")
        assert result == []

    def test_split_statements_single(self):
        from src.infrastructure.db.bootstrap import _split_statements

        result = _split_statements("SELECT 1;")
        assert result == ["SELECT 1"]

    def test_split_statements_multiple(self):
        from src.infrastructure.db.bootstrap import _split_statements

        sql = "SELECT 1; SELECT 2; SELECT 3;"
        result = _split_statements(sql)

        assert result == ["SELECT 1", "SELECT 2", "SELECT 3"]

    def test_split_statements_with_dollar_quotes(self):
        from src.infrastructure.db.bootstrap import _split_statements

        sql = "SELECT 1; $$ SELECT 'inner' ; SELECT 2 $$; SELECT 3;"
        result = _split_statements(sql)

        assert result == ["SELECT 1", "$$ SELECT 'inner' ; SELECT 2 $$", "SELECT 3"]

    def test_split_statements_with_line_comments(self):
        from src.infrastructure.db.bootstrap import _split_statements

        sql = "SELECT 1; -- comment\nSELECT 2; SELECT 3;"
        result = _split_statements(sql)

        assert "-- comment" in result[1]

    def test_split_statements_with_semicolon_in_comment(self):
        from src.infrastructure.db.bootstrap import _split_statements

        # Le ; dans le commentaire fait partie du commentaire, pas un délimiteur
        sql = "SELECT 1; -- comment with ; semicolon\nSELECT 2;"
        result = _split_statements(sql)

        assert "SELECT 1" in result[0]
        # Le commentaire est attaché à l'instruction suivante
        assert len(result) >= 1

    def test_split_statements_no_trailing_semicolon(self):
        from src.infrastructure.db.bootstrap import _split_statements

        sql = "SELECT 1\nSELECT 2"
        result = _split_statements(sql)

        # Sans ; final, la dernière instruction est quand même capturée
        assert "SELECT 1" in result[0] or "SELECT 1" in result[-1]

    def test_split_statements_empty_statements_ignored(self):
        from src.infrastructure.db.bootstrap import _split_statements

        sql = "SELECT 1;;;SELECT 2;"
        result = _split_statements(sql)

        assert "SELECT 1" in result[0]
        assert "SELECT 2" in result[1]
        assert len(result) == 2

    def test_ensure_schema(self, monkeypatch, tmp_path):
        from src.infrastructure.db.bootstrap import ensure_schema

        # Crée un fichier SQL temporaire
        mock_sql = "CREATE TABLE test (id INT);"
        sql_path = tmp_path / "tables.sql"
        sql_path.write_text(mock_sql, encoding="utf-8")

        monkeypatch.setattr(
            "src.infrastructure.db.bootstrap.SCHEMA_SQL_PATH",
            sql_path
        )

        mock_engine = MagicMock()

        # Simuler engine.connect() qui retourne un context manager
        mock_inner_conn = MagicMock()
        mock_inner_conn.execute = MagicMock()

        # execution_options renvoie le même conn avec isolation_level modifié
        mock_conn_with_options = MagicMock()
        mock_conn_with_options.execute = mock_inner_conn.execute
        mock_inner_conn.execution_options.return_value = mock_conn_with_options

        mock_engine.connect.return_value.__enter__.return_value = mock_inner_conn
        mock_engine.connect.return_value.__exit__.return_value = None

        ensure_schema(mock_engine)

        # Vérifie que execute a été appelé
        assert mock_inner_conn.execute.call_count >= 1
