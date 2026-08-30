"""Tests de la conversion HTML → texte du scraper d'URL
(``src/interfaces/scrapers/url/scraper.py`` — ``URLScraper._html_to_text``).

``fetch_text`` (Playwright) n'est pas exécuté ici : on teste la conversion pure
du HTML en texte brut, et en particulier la **réinjection des ``href``**
(section ``LINKS DE LA PAGE``) dont le chemin « liste » a besoin pour extraire
les URLs des offres (les ``href`` sont perdus par la conversion en texte).
"""

from src.core.scoring.url_offer_extractor import MAX_PAGE_CHARS
from src.interfaces.scrapers.url.scraper import MAX_PAGE_LINKS, URLScraper


def _convert(html: str, base_url: str = "") -> str:
    return URLScraper._html_to_text(html, base_url)


def test_strips_scripts_and_normalizes_spaces():
    html = (
        "<html><body><script>var x = 1;</script>"
        "<p>Offre  <b>Data</b>  Engineer</p><style>p{}</style></body></html>"
    )
    assert _convert(html) == "Offre Data Engineer"


def test_preserves_paragraph_and_list_structure():
    """La structure de la page (paragraphes, listes à puces) survit à la
    conversion en texte : c'est ce que voit le LLM d'extraction, qui doit la
    retranscrire dans la description — une offre affichée en blocs ne doit pas
    arriver en base comme un seul paragraphe compact."""
    html = (
        "<html><body>"
        "<p>Venez rejoindre le leader.</p>"
        "<p>Marie Blachère recrute !</p>"
        "<ul>"
        "<li>Fabriquer les produits de boulangerie</li>"
        "<li>Contrôler la qualité des produits</li>"
        "</ul>"
        "<p>CDI 35h/semaine</p>"
        "</body></html>"
    )
    text = _convert(html)
    # Paragraphes sur des lignes distinctes.
    assert "Venez rejoindre le leader.\n" in text
    assert "Marie Blachère recrute !\n" in text
    # Items de liste préfixés par « - », dans l'ordre du document.
    assert "- Fabriquer les produits de boulangerie" in text
    assert "- Contrôler la qualité des produits" in text
    assert text.index("Fabriquer") < text.index("Contrôler")


def test_br_becomes_newline():
    html = "<html><body><div>Ligne 1<br>Ligne 2</div></body></html>"
    text = _convert(html)
    assert "Ligne 1\nLigne 2" in text


def test_no_links_no_section():
    html = "<html><body>Une simple page sans lien.</body></html>"
    text = _convert(html, "https://example.com/")
    assert "LINKS DE LA PAGE" not in text


def test_injects_page_links_with_anchor_text():
    html = (
        "<html><body>"
        '<a href="https://example.com/offres/data-engineer">Data Engineer H/F</a>'
        "</body></html>"
    )
    text = _convert(html, "https://example.com/")
    assert "LINKS DE LA PAGE :" in text
    assert "- https://example.com/offres/data-engineer (Data Engineer H/F)" in text


def test_resolves_relative_links_against_base_url():
    html = '<html><body><a href="/offres/detail/123">Boulanger (H/F)</a></body></html>'
    text = _convert(
        html, "https://candidat.francetravail.fr/offres/recherche?motsCles=Boulanger"
    )
    assert "https://candidat.francetravail.fr/offres/detail/123" in text


def test_skips_non_http_and_fragment_links():
    html = (
        "<html><body>"
        '<a href="javascript:void(0)">JS</a>'
        '<a href="mailto:x@y.fr">mail</a>'
        '<a href="tel:+331">téléphone</a>'
        '<a href="#section">ancre</a>'
        '<a href="https://example.com/offres/a">Offre A</a>'
        "</body></html>"
    )
    text = _convert(html, "https://example.com/")
    assert "javascript:" not in text
    assert "mailto:" not in text
    assert "tel:" not in text
    assert "#section" not in text
    assert "- https://example.com/offres/a" in text


def test_deduplicates_links_preserving_order():
    html = (
        "<html><body>"
        '<a href="https://example.com/o1">A</a>'
        '<a href="https://example.com/o1">A bis</a>'
        '<a href="https://example.com/o2">B</a>'
        "</body></html>"
    )
    text = _convert(html, "https://example.com/")
    assert text.count("- https://example.com/o1") == 1
    assert text.index("https://example.com/o1") < text.index("https://example.com/o2")


def test_caps_number_of_links():
    offers = "".join(
        f'<a href="https://example.com/o{i}">Offre {i}</a>'
        for i in range(MAX_PAGE_LINKS + 10)
    )
    text = _convert(f"<html><body>{offers}</body></html>", "https://example.com/")
    assert text.count("- https://example.com/o") == MAX_PAGE_LINKS


def test_excludes_links_from_secondary_containers():
    """Les liens des conteneurs secondaires (nav, header, footer, aside) ne sont
    pas réinjectés dans LINKS DE LA PAGE.

    Sur une page de recherche affichant un carrousel « dernières offres » dans
    le header/nav (ex. Free-Work), ces liens arrivaient EN PREMIER dans la
    section LINKS (ordre du document) et le LLM, invité à renvoyer les URLs
    d'offres « dans l'ordre de la page », les sélectionnait en priorité — d'où
    des offres ingérées sans rapport avec la recherche. Seuls les liens du
    contenu principal sont injectés.
    """
    html = (
        "<html><body>"
        "<header>"
        '<a href="https://example.com/recent-1">Senior Software Engineer</a>'
        "</header>"
        "<nav>"
        '<a href="https://example.com/recent-2">TESTER QA (H/F)</a>'
        "</nav>"
        "<main>"
        '<a href="https://example.com/offres/developpeur-ia">Développeur IA</a>'
        "</main>"
        "<aside>"
        '<a href="https://example.com/recent-3">Offre sponsorisée</a>'
        "</aside>"
        "<footer>"
        '<a href="https://example.com/mentions-legales">Mentions légales</a>'
        "</footer>"
        "</body></html>"
    )
    text = _convert(html, "https://example.com/")
    assert "LINKS DE LA PAGE" in text
    # Le lien du contenu principal est conservé.
    assert "- https://example.com/offres/developpeur-ia" in text
    # Les liens des conteneurs secondaires ne sont pas injectés.
    assert "recent-1" not in text
    assert "recent-2" not in text
    assert "recent-3" not in text
    assert "mentions-legales" not in text


def test_header_nested_in_main_content_is_not_secondary():
    """Un ``<header>`` IMBRIQUÉ dans le contenu principal n'est pas un conteneur
    secondaire : c'est du contenu, pas du chrome de page.

    Certains sites (ex. Hellowork) enveloppent leurs cartes de résultats dans un
    ``<header>`` à l'intérieur de la section principale. Régression 2026-08-28 :
    la correction « conteneurs secondaires » excluait tous les liens sous un
    ``<header>`` — les URLs d'offres disparaissaient de la section LINKS DE LA
    PAGE et le LLM, sans href à recopier, inventait des URLs slug (HTTP 404 à la
    récupération individuelle de chaque offre).
    """
    html = (
        "<html><body>"
        "<header>"  # chrome de page (racine) : exclu
        '<a href="https://example.com/recent-1">Senior Software Engineer</a>'
        "</header>"
        "<section>"  # contenu principal
        "<header>"  # enveloppe des cartes de résultats (Hellowork)
        '<a href="https://example.com/offres/developpeur-ia">Développeur IA</a>'
        "</header>"
        "</section>"
        "<footer>"
        '<a href="https://example.com/mentions-legales">Mentions légales</a>'
        "</footer>"
        "</body></html>"
    )
    text = _convert(html, "https://example.com/")
    assert "LINKS DE LA PAGE" in text
    # L'offre du contenu principal (dans un <header> imbriqué) est conservée.
    assert "- https://example.com/offres/developpeur-ia" in text
    # Le header de page et le footer restent exclus (chrome).
    assert "recent-1" not in text
    assert "mentions-legales" not in text


def test_links_preserved_when_visible_text_overflows():
    """Avec un texte visible énorme, la section LINKS est préservée : un budget
    lui est réservé, le texte visible est tronqué pour tenir."""
    long_text = "x" * (MAX_PAGE_CHARS * 2)
    html = (
        f"<html><body>{long_text}"
        '<a href="https://example.com/offre">Offre</a></body></html>'
    )
    text = _convert(html, "https://example.com/")
    assert "LINKS DE LA PAGE :" in text
    assert "- https://example.com/offre" in text
    # Tout tient dans la borne (le caractère de coupure « … » peut l'atteindre).
    assert len(text) <= MAX_PAGE_CHARS + 1


def test_truncates_to_max_page_chars_without_links():
    long_text = "x" * (MAX_PAGE_CHARS * 2)
    text = _convert(f"<html><body>{long_text}</body></html>")
    assert len(text) == MAX_PAGE_CHARS + 1  # MAX_PAGE_CHARS + « … »
    assert text.endswith("…")
