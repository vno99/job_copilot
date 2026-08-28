"""Récupération du texte d'une page web via Playwright (feature « Ajouter des
offres d'emploi »).

``URLScraper.fetch_text(url)`` récupère le HTML de la page avec un navigateur
headless (Chromium via Playwright) puis le convertit en texte brut exploitable
par le LLM d'extraction (``url_offer_extractor.extract_offer``).

Playwright est importé **paresseusement** (dans ``_fetch_html_with_playwright``)
pour que l'import de ce module ne dépende pas du paquet ``playwright`` installé
(les tests unitaires qui mockent ``fetch_text`` n'ont pas besoin du navigateur).

Le schéma de l'URL est validé (``normalize_url``) : seuls ``http``/``https``
sont acceptés, et l'hôte ne doit pas résoudre vers une adresse privée ou
réservée (barrière SSRF, appliquée aussi après chaque redirection).
"""

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

from config.logger_config import setup_logging
from src.core.html_text import element_to_text
from src.core.scoring.url_offer_extractor import MAX_PAGE_CHARS, URLScrapingError

logger = setup_logging(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

# Liens de la page réinjectés dans le texte vu par le LLM : la conversion en
# texte perd les ``href``, or le chemin « liste » a besoin des URLs des offres.
# Bornes de sécurité (coût / latence du prompt).
MAX_PAGE_LINKS = 80        # nombre maximal de liens injectés
_PAGE_LINK_TEXT_MAX = 60   # longueur maximale du texte d'ancre affiché par lien
_VISIBLE_TEXT_MIN = 2000   # budget minimal garanti au texte visible

# Conteneurs dont les liens ne sont PAS réinjectés dans LINKS DE LA PAGE :
# navigation, en-tête, pied de page, barre latérale portent le contenu
# secondaire. Sans cette exclusion, un carrousel « dernières offres » logé dans
# le header/nav (ex. Free-Work) voyait ses liens arriver EN PREMIER dans la
# section LINKS (ordre du document) — et le LLM, invité à renvoyer les URLs
# d'offres « dans l'ordre de la page », sélectionnait en priorité ces offres
# hors critères de recherche (cause racine d'ingestions non pertinentes).
SECONDARY_LINK_TAGS = ("nav", "header", "footer", "aside")


def _is_private_ip(address: str) -> bool:
    """L'adresse IP est-elle privée, loopback, link-local, réservée ou indéfinie ?"""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_private_host(hostname: str) -> bool:
    """L'URL pointe-t-elle vers un hôte privé/réservé (SSRF) ?

    - Hostname littéralement une IP → test direct (ex. ``http://127.0.0.1/``).
    - Sinon, résolution DNS : si **une seule** adresse résolue est privée, l'hôte
      est refusé (ex. un hostname interne résolu par le DNS du déploiement vers
      un ``10.x``). Un échec de résolution laisse passer (``False``) : si l'hôte
      n'est pas résoluble, Playwright ne pourra pas non plus le joindre, donc
      rien de privé n'est récupérable.
    """
    if not hostname:
        return False
    if _is_private_ip(hostname):
        return True
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    return any(_is_private_ip(info[4][0]) for info in infos)


def _in_secondary_container(anchor) -> bool:
    """Le lien se trouve-t-il dans un conteneur secondaire (``nav``, ``header``,
    ``footer``, ``aside``) ?

    Ces conteneurs portent le contenu secondaire de la page (navigation, menu,
    pied de page, barre latérale, carrousels d'offres « récentes » logés dans le
    header). Leurs liens ne sont pas des offres du contenu principal : les
    injecter dans LINKS DE LA PAGE biaisait l'extraction d'une liste — le LLM,
    invité à renvoyer les URLs d'offres « dans l'ordre de la page », choisissait
    en priorité les liens d'un carrousel « dernières offres » hors critères de
    recherche, en tête de liste (ex. Free-Work).
    """
    element = anchor
    while element is not None:
        tag = getattr(element, "tag", None)
        if isinstance(tag, str) and tag.lower() in SECONDARY_LINK_TAGS:
            return True
        element = element.getparent()
    return False


def _collect_page_links(tree, base_url: str) -> list[str]:
    """Liens http(s) de la page (``<a href>``), résolus en URL absolues.

    Un court extrait du texte de chaque lien est affiché entre parenthèses pour
    que le LLM distingue les liens d'offres (la carte porte le titre du poste)
    des liens internes (sélection, navigation…). Les liens des conteneurs
    secondaires (``_in_secondary_container``) sont exclus : leur injection
    biaisait l'extraction des offres d'une liste (liens d'un carrousel du header
    sélectionnés en priorité par le LLM). Borné à ``MAX_PAGE_LINKS``, ordre du
    document conservé, doublons retirés. Aucun fetch n'est fait ici : les URLs
    retournées seront validées (barrière SSRF) au moment où le service les
    récupérera individuellement.
    """
    links: list[str] = []
    seen: set[str] = set()
    for anchor in tree.xpath("//a[@href]"):
        if _in_secondary_container(anchor):
            continue
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        try:
            absolute = urljoin(base_url, href)
        except ValueError:
            continue
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        label = re.sub(r"\s+", " ", " ".join(anchor.itertext())).strip()
        line = f"- {absolute}"
        if label:
            line += f" ({label[:_PAGE_LINK_TEXT_MAX]})"
        links.append(line)
        if len(links) >= MAX_PAGE_LINKS:
            break
    return links


def normalize_url(url: str) -> str:
    """Valide et normalise une URL pour la récupération et le dédoublonnage.

    Exige un schéma ``http``/``https``, un hostname non vide et un hôte **non
    privé** (barrière SSRF : pas d'IP privée/loopback/link-local résolue),
    retire le fragment (``#…``) pour que le même site avec/sans fragment soit
    dédoublonné de façon fiable.

    Raises:
        URLScrapingError: URL invalide (schéma non autorisé, hostname vide,
            hôte privé).
    """
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise URLScrapingError(
            "URL invalide : seuls les schémas http/https sont autorisés"
        )
    if _is_private_host(parts.hostname):
        raise URLScrapingError(
            f"URL refusée : l'hôte '{parts.hostname}' pointe vers une adresse privée"
        )
    return parts._replace(fragment="").geturl()


class URLScraper:
    """Récupère le texte brut d'une page web via Playwright (Chromium headless)."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 2.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def fetch_text(self, url: str) -> str:
        """HTML (Playwright) → texte brut exploitable par le LLM.

        Args:
            url: URL de la page à récupérer (normalisée par ``normalize_url``).

        Returns:
            Le texte de la page, espaces blancs normalisés, borné à
            ``MAX_PAGE_CHARS`` caractères.

        Raises:
            URLScrapingError: URL invalide, échec définitif du fetch, HTML vide
                ou non convertible en texte.
        """
        url = normalize_url(url)
        html = self._fetch_html_with_playwright(url)
        if not html:
            raise URLScrapingError(f"Récupération impossible de {url}")
        text = self._html_to_text(html, url)
        if not text:
            raise URLScrapingError(f"La page {url} ne contient aucun texte exploitable")
        return text

    def _fetch_html_with_playwright(self, url: str) -> str | None:
        """Récupère le HTML rendu d'une page via Chromium headless (retries).

        Pattern calqué sur ``HelloworkScraper.fetch_html_with_playwright``.
        Playwright est importé ici, au moment de l'appel, pour ne pas rendre ce
        module dépendant du paquet à l'import.

        Returns:
            Le HTML complet après exécution du JS, ou ``None`` après échec
            définitif de toutes les tentatives.
        """
        from playwright.sync_api import (  # import paresseux
            TimeoutError as PlaywrightTimeoutError,
        )
        from playwright.sync_api import sync_playwright

        logger.info("Traitement de l'url: %s", url)

        for attempt in range(self.max_retries + 1):
            browser = None
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                            "--disable-web-security",
                            "--disable-features=IsolateOrigins,site-per-process",
                            "--disable-gpu",
                            "--window-size=1920,1080",
                        ],
                    )
                    context = browser.new_context(
                        user_agent=USER_AGENT,
                        viewport={"width": 1280, "height": 900},
                        locale="fr-FR",
                        timezone_id="Europe/Paris",
                        java_script_enabled=True,
                    )
                    page = context.new_page()

                    try:
                        response = page.goto(
                            url, wait_until="networkidle", timeout=20000
                        )
                    except PlaywrightTimeoutError:
                        logger.warning(
                            "Timeout lors du chargement de %s, tentative %d",
                            url,
                            attempt + 1,
                        )
                        continue

                    if response and response.status >= 400:
                        logger.warning("HTTP %s pour %s", response.status, url)
                        continue

                    # Barrière SSRF après redirection : une redirection peut mener
                    # vers un hôte privé (ex. 302 vers http://127.0.0.1/) même si
                    # l'URL initiale était publique. On refuse alors le contenu.
                    final_url = page.url
                    final_host = urlsplit(final_url).hostname or ""
                    if _is_private_host(final_host):
                        logger.warning(
                            "Redirection vers un hôte privé refusée : %s", final_url
                        )
                        continue

                    page.wait_for_load_state("networkidle", timeout=10000)
                    html = page.content()

                    if not html or len(html) < 100:
                        logger.warning(
                            "HTML trop court (%d caractères) pour %s",
                            len(html or ""),
                            url,
                        )
                        continue

                    logger.info("HTML récupéré avec succès (%d caractères)", len(html))
                    return html

            except PlaywrightTimeoutError as exc:
                logger.warning("Timeout Playwright, tentative %d : %s", attempt + 1, exc)
            except Exception as exc:
                logger.error("Erreur inattendue, tentative %d : %s", attempt + 1, exc)
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass

            if attempt < self.max_retries:
                sleep_time = self.backoff_factor**attempt
                logger.info(
                    "Attente de %.2fs avant la tentative %d", sleep_time, attempt + 2
                )
                import time

                time.sleep(sleep_time)

        logger.error("Échec définitif après %d tentatives pour %s", self.max_retries + 1, url)
        return None

    @staticmethod
    def _html_to_text(html: str, base_url: str = "") -> str:
        """Convertit du HTML en texte brut (lxml), sans le bruit des scripts.

        Retire d'abord ``<script>``/``<style>``/``<noscript>``/``<svg>`` puis
        convertit la page en texte via ``element_to_text`` : la structure des
        blocs (paragraphes, listes à puces) est préservée par des retours à la
        ligne — une offre affichée en blocs ne doit pas arriver aplatée en un
        seul paragraphe (le LLM d'extraction a besoin de la structure pour la
        retranscrire dans la description).
        Les ``href`` (perdus par la conversion en texte) sont réinjectés à la
        fin sous forme de liens absolus avec leur texte d'ancre (``LINKS DE LA
        PAGE``) : le LLM d'extraction a besoin des URLs des offres pour une
        liste. Un budget est réservé aux liens, le texte visible est tronqué
        pour tenir dans ``MAX_PAGE_CHARS`` (plancher ``_VISIBLE_TEXT_MIN``).
        """
        from lxml import etree

        tree = etree.HTML(html)
        if tree is None:
            return ""
        for node in tree.xpath("//script | //style | //noscript | //svg"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        text = element_to_text(tree)

        links = _collect_page_links(tree, base_url)
        if links:
            section = "\n\nLINKS DE LA PAGE :\n" + "\n".join(links)
            budget = max(_VISIBLE_TEXT_MIN, MAX_PAGE_CHARS - len(section))
            if len(text) > budget:
                text = text[:budget] + "…"
            text += section
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + "…"
        return text
