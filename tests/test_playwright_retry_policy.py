"""Tests de la politique de retry du fetch Playwright
(``src/interfaces/scrapers/url/scraper.py::URLScraper._fetch_html_with_playwright``).

Le navigateur n'est pas démarré : on mocke ``sync_playwright`` pour piloter
les réponses HTTP renvoyées par ``page.goto``. La politique vise à ne **pas**
ré-essayer indéfiniment les erreurs définitives (4xx, redirection vers hôte
privé) — un 404 ne sera jamais résolu par une nouvelle tentative.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.interfaces.scrapers.url.scraper import URLScraper


def _mock_response(status: int, url: str) -> SimpleNamespace:
    """Faux objet ``Response`` Playwright (seuls ``status`` et l'URL finale sont
    consultés par le code de fetch)."""
    return SimpleNamespace(status=status, url=url)


def _mock_playwright(status_sequence, final_url="https://example.com/page"):
    """Construit un faux contexte ``sync_playwright`` qui renvoie les statuts
    successifs de ``status_sequence`` (un par appel à ``goto``). Le ``goto``
    met à jour ``page.url`` à ``final_url`` (utilisé pour la barrière SSRF).
    """
    statuses = list(status_sequence)
    page = MagicMock()
    page.goto.side_effect = lambda _url, **kwargs: _mock_response(statuses.pop(0), final_url)
    page.url = final_url
    # HTML assez long pour passer le filtre ``len(html) < 100`` du scraper.
    page.content.return_value = "<html><body>" + ("x" * 200) + "</body></html>"

    context = MagicMock()
    context.new_page.return_value = page

    browser = MagicMock()
    browser.new_context.return_value = context

    chromium = MagicMock()
    chromium.launch.return_value = browser

    playwright = MagicMock()
    playwright.chromium = chromium

    sync_playwright = MagicMock()
    sync_playwright.return_value.__enter__ = MagicMock(return_value=playwright)
    sync_playwright.return_value.__exit__ = MagicMock(return_value=False)
    return sync_playwright


class TestRetryableStatusCodes:
    """Codes HTTP transitoires : retry autorisé."""

    def test_500_is_retried_until_exhausted(self):
        """5xx : retry jusqu'à ``max_retries + 1`` tentatives, puis abandon."""
        sync_pw = _mock_playwright([500] * 10)
        with patch(
            "src.interfaces.scrapers.url.scraper.sync_playwright", sync_pw, create=True
        ):
            # Import paresseux : importer après le patch pour qu'il voie le mock.
            with patch.dict(
                "sys.modules",
                {
                    "playwright.sync_api": MagicMock(
                        sync_playwright=sync_pw,
                        TimeoutError=type("TimeoutError", (Exception,), {}),
                    )
                },
            ):
                scraper = URLScraper(max_retries=2)
                result = scraper._fetch_html_with_playwright("https://example.com/")
        # 3 tentatives (max_retries=2) + abandon → None.
        assert result is None

    def test_429_is_retried(self):
        """429 Too Many Requests : transitoire, retry."""
        sync_pw = _mock_playwright([429, 200])
        # Premier 429 puis 200 : on s'attend à un succès.
        with patch.dict(
            "sys.modules",
            {
                "playwright.sync_api": MagicMock(
                    sync_playwright=sync_pw,
                    TimeoutError=type("TimeoutError", (Exception,), {}),
                )
            },
        ):
            scraper = URLScraper(max_retries=2)
            result = scraper._fetch_html_with_playwright("https://example.com/")
        assert result is not None


class TestNonRetryableStatusCodes:
    """Codes HTTP définitifs : arrêt immédiat, pas de retry."""

    def test_404_stops_after_one_attempt(self):
        """404 Not Found : définitif, le scraper n'insiste pas."""
        # 5 tentatives demandées, mais le 404 doit faire retourner None
        # dès la première.
        sync_pw = _mock_playwright([404])
        with patch.dict(
            "sys.modules",
            {
                "playwright.sync_api": MagicMock(
                    sync_playwright=sync_pw,
                    TimeoutError=type("TimeoutError", (Exception,), {}),
                )
            },
        ):
            scraper = URLScraper(max_retries=5)
            result = scraper._fetch_html_with_playwright("https://example.com/missing")
        assert result is None

    def test_403_stops_after_one_attempt(self):
        """403 Forbidden : définitif."""
        sync_pw = _mock_playwright([403])
        with patch.dict(
            "sys.modules",
            {
                "playwright.sync_api": MagicMock(
                    sync_playwright=sync_pw,
                    TimeoutError=type("TimeoutError", (Exception,), {}),
                )
            },
        ):
            scraper = URLScraper(max_retries=3)
            result = scraper._fetch_html_with_playwright("https://example.com/forbidden")
        assert result is None

    def test_410_stops_after_one_attempt(self):
        """410 Gone : définitif (la ressource a disparu)."""
        sync_pw = _mock_playwright([410])
        with patch.dict(
            "sys.modules",
            {
                "playwright.sync_api": MagicMock(
                    sync_playwright=sync_pw,
                    TimeoutError=type("TimeoutError", (Exception,), {}),
                )
            },
        ):
            scraper = URLScraper(max_retries=3)
            result = scraper._fetch_html_with_playwright("https://example.com/gone")
        assert result is None


class TestPrivateHostRedirect:
    """Redirection vers un hôte privé : refus immédiat, pas de retry."""

    def test_redirect_to_private_host_stops_immediately(self):
        """Une redirection vers 127.0.0.1 (SSRF) n'est pas retentée : la situation
        est définie par la réponse du serveur, retry ne changera rien."""
        sync_pw = _mock_playwright(
            [200], final_url="http://127.0.0.1:8080/admin"
        )
        with patch.dict(
            "sys.modules",
            {
                "playwright.sync_api": MagicMock(
                    sync_playwright=sync_pw,
                    TimeoutError=type("TimeoutError", (Exception,), {}),
                )
            },
        ):
            scraper = URLScraper(max_retries=3)
            result = scraper._fetch_html_with_playwright("https://example.com/")
        assert result is None
