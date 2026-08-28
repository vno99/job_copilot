"""Application du schéma applicatif.

Le schéma vit dans ``sql/tables.sql`` (source de vérité, DDL idempotent).
Cette fonction l'exécute sur un engine donné.
"""

from pathlib import Path
from typing import List

from sqlalchemy import Engine, text

from src.config.settings import PROJECT_ROOT

SCHEMA_SQL_PATH = PROJECT_ROOT / "sql" / "tables.sql"


def _split_statements(sql: str) -> List[str]:
    """Découpe ``tables.sql`` en instructions au ``;``, **hors** blocs
    dollar-quotés (``$$...$$``) et commentaires ``--``.

    Un ``DO`` block PL/pgSQL contient des ``;`` internes (délimiteurs de
    commandes) qui ne doivent pas être découpés ; un ``;`` dans un commentaire
    ne doit pas non plus fendre une instruction. Conserve le comportement
    antérieur pour le reste (blancs retirés, commentaires conservés avec
    l'instruction suivante — inoffensifs pour le moteur SQL).
    """
    statements: List[str] = []
    buf: List[str] = []
    in_dollar = False
    in_line_comment = False
    i = 0
    n = len(sql)
    while i < n:
        if in_dollar:
            if sql.startswith("$$", i):
                buf.append("$$")
                in_dollar = False
                i += 2
            else:
                buf.append(sql[i])
                i += 1
            continue
        if in_line_comment:
            if sql[i] == "\n":
                in_line_comment = False
            buf.append(sql[i])
            i += 1
            continue
        if sql.startswith("$$", i):
            buf.append("$$")
            in_dollar = True
            i += 2
            continue
        if sql.startswith("--", i):
            buf.append("--")
            in_line_comment = True
            i += 2
            continue
        if sql[i] == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(sql[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def ensure_schema(engine: Engine) -> None:
    """Exécute ``sql/tables.sql`` (idempotent via IF NOT EXISTS).

    Le DDL contient des ``CREATE INDEX CONCURRENTLY`` et des ``DO`` blocks que
    PostgreSQL interdit dans une transaction : chaque instruction est donc
    exécutée en autocommit. L'idempotence repose sur les ``IF NOT EXISTS`` de
    ``tables.sql`` et sur les garde-fous des migrations one-shot (``DO`` blocks).

    Args:
        engine (Engine): Engine connecté à la base applicative.
    """
    sql = Path(SCHEMA_SQL_PATH).read_text(encoding="utf-8")
    statements = _split_statements(sql)

    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        for stmt in statements:
            conn.execute(text(stmt))
