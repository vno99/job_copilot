"""Tests du découpage SQL de ``ensure_schema`` (``src/infrastructure/db/bootstrap.py``).

Aucune base requise : ``_split_statements`` est pure. Couvre notamment le
traitement des blocs dollar-quotés (``DO`` blocks PL/pgSQL aux ``;`` internes)
et des commentaires ``--``.
"""

from src.infrastructure.db.bootstrap import _split_statements


def test_split_simple_statements():
    sql = "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);"
    assert _split_statements(sql) == [
        "CREATE TABLE a (id INT)",
        "CREATE TABLE b (id INT)",
    ]


def test_split_keeps_dollar_block_intact():
    """Un ``DO $$…$$`` contient des ``;`` internes (délimiteurs PL/pgSQL) qui ne
    doivent pas être découpés : le bloc reste une seule instruction."""
    sql = (
        "CREATE TABLE t (id INT);\n"
        "DO $$ BEGIN IF true THEN DELETE FROM t; END IF; END $$;\n"
        "CREATE INDEX i ON t (id);"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 3
    assert stmts[0] == "CREATE TABLE t (id INT)"
    assert stmts[1].startswith("DO $$")
    assert stmts[1].endswith("END $$")
    # Le ``;`` interne au bloc n'a pas découpé.
    assert "DELETE FROM t;" in stmts[1]
    assert stmts[2] == "CREATE INDEX i ON t (id)"


def test_split_ignores_semicolon_in_line_comment():
    sql = "-- note ; avec point-virgule\nCREATE TABLE t (id INT);\n"
    # Le ``;`` du commentaire ne fend pas l'instruction ; le commentaire reste
    # attaché à l'instruction suivante (inoffensif pour le moteur SQL).
    assert _split_statements(sql) == [
        "-- note ; avec point-virgule\nCREATE TABLE t (id INT)"
    ]


def test_split_tables_sql_real_file():
    """Le fichier réel est découpé en instructions cohérentes : les deux ``DO``
    blocks (migration cv_version, purge des index INVALID) restent entiers et le
    nombre d'instructions est plausible (~30 CREATE/ALTER + 2 DO)."""
    from src.infrastructure.db.bootstrap import SCHEMA_SQL_PATH

    stmts = _split_statements(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
    assert len(stmts) > 20
    # Les commentaires ``--`` restent attachés à l'instruction qu'ils précèdent :
    # on détecte le bloc par son contenu plutôt que par le début de la chaîne.
    do_blocks = [s for s in stmts if "DO $$" in s and s.rstrip().endswith("$$")]
    assert len(do_blocks) == 2
    for block in do_blocks:
        assert block.rstrip().endswith("$$")
        assert ";" in block.split("$$")[1]  # des ; internes, non découpés
