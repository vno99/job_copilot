"""Conversion d'un CV Markdown en PDF (``xhtml2pdf``).

Les CV générés sont stockés en Markdown (``cv_text``) ; cette conversion produit
un PDF vectoriel (texte sélectionnable) pour le téléchargement via l'API.
"""

from io import BytesIO

from markdown import markdown
from xhtml2pdf import pisa

# CSS minimal compatible xhtml2pdf (pas de flexbox/grid) : page A4, marges,
# titres, listes, mise en évidence et tableaux Markdown. Les bordures sont
# portées par les cellules (``th``/``td``) : xhtml2pdf gère mal
# ``border-collapse``.
_CSS = """
@page { size: A4; margin: 2cm; }
body { font-family: Helvetica; font-size: 11px; line-height: 1.5; color: #111; }
h1 { font-size: 18px; margin-bottom: 8px; }
h2 { font-size: 14px; border-bottom: 1px solid #999; padding-bottom: 2px; margin-top: 16px; }
h3 { font-size: 12px; margin-top: 12px; }
ul { margin: 4px 0 8px 0; }
li { margin-bottom: 2px; }
strong { font-weight: bold; }
pre, code { font-family: Courier; }
table { width: 100%; margin: 4px 0 8px 0; }
th, td { border: 1px solid #999; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #eee; }
"""


class PDFGenerationError(Exception):
    """La conversion Markdown → PDF a échoué (rendu ``xhtml2pdf`` en erreur)."""


def _markdown_to_html(markdown_text: str) -> str:
    """Markdown → HTML, extension ``tables`` activée (tableaux GFM).

    Sans l'extension ``tables``, python-markdown rend un tableau Markdown comme
    du texte brut (les ``|`` et le séparateur ``|---|---|`` apparaissent tels
    quels). Elle est indispensable pour le « tableau des compétences clés » que
    le LLM peut produire dans un CV.
    """
    return markdown(markdown_text, extensions=["tables"])


def markdown_to_pdf(markdown_text: str) -> bytes:
    """Convertit un CV Markdown en bytes PDF.

    Raises:
        PDFGenerationError: si le rendu ``xhtml2pdf`` signale une erreur.
    """
    html_body = _markdown_to_html(markdown_text)
    html = (
        "<html><head><style>"
        + _CSS
        + "</style></head><body>"
        + html_body
        + "</body></html>"
    )
    buf = BytesIO()
    result = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    if result.err:
        raise PDFGenerationError(
            f"Conversion Markdown → PDF en échec (pisa.err={result.err})"
        )
    return buf.getvalue()
