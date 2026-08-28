"""Tests unitaires de la conversion d'un CV Markdown en PDF (``src.core.pdf``).

Aucun LLM ni base de données requis.
"""

from src.core.pdf import _markdown_to_html, markdown_to_pdf


def test_markdown_to_pdf_returns_pdf_bytes():
    """Un Markdown simple produit un PDF (en-tête ``%PDF``, non vide)."""
    data = markdown_to_pdf("# Titre\n\n## Section\n\n- point 1\n- point 2\n")
    assert data[:5] == b"%PDF-"
    assert len(data) > 100


def test_markdown_to_pdf_handles_accents():
    """Les accents français sont conservés (police reportlab Latin-1)."""
    data = markdown_to_pdf(
        "## Compétences\n\nÉtudes supérieures, expérience en **français**."
    )
    assert data[:5] == b"%PDF-"


def test_markdown_to_html_renders_gfm_table():
    """Un tableau Markdown (compétences clés) devient un vrai ``<table>``.

    Sans l'extension ``tables``, le tableau resterait du texte brut (les ``|``
    et le séparateur ``|---|---|`` affichés tels quels).
    """
    html = _markdown_to_html(
        "## Compétences clés\n\n"
        "| Domaine | Technologies |\n"
        "|---|---|\n"
        "| Data Engineering | Python, SQL |\n"
        "| Cloud & DevOps | AWS S3 |\n"
    )
    assert "<table>" in html
    assert "<th>Domaine</th>" in html
    assert "<th>Technologies</th>" in html
    assert "<td>Data Engineering</td>" in html
    assert "<td>Python, SQL</td>" in html
    assert "<td>Cloud &amp; DevOps</td>" in html


def test_markdown_to_pdf_renders_table():
    """Le rendu PDF d'un CV contenant un tableau ne lève pas d'erreur."""
    data = markdown_to_pdf(
        "## Compétences clés\n\n"
        "| Domaine | Technologies |\n"
        "|---|---|\n"
        "| Data Engineering | Python, SQL |\n"
    )
    assert data[:5] == b"%PDF-"
