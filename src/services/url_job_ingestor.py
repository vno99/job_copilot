"""Ingestion d'offres d'emploi depuis une URL (feature « Ajouter des offres
d'emploi »).

``URLJobIngestorService.run(url, max_offers)`` enchaîne : validation/normalisation
de l'URL, récupération de la page (Playwright), classification LLM
(``extract_page`` — ministral-14b-latest). Deux chemins :

- **offre unique** (la page EST l'offre) : le contenu est déjà extrait par le
  LLM, on dédoublonne sur l'URL soumise (409 si déjà en base) puis on upsert ;
- **liste d'offres** : le LLM renvoie les URLs des offres. On écarte celles déjà
  en base (colonne ``url``, indépendamment de la source), puis on récupère
  individuellement chacune des ``max_offers`` premières URLs **nouvelles**
  (fetch Playwright + extraction mono-offre) et on les upsert via le pipeline
  existant (``normalize_job_offer`` → ``upsert_many``). Les offres déjà
  présentes ne sont **pas** mises à jour ; un échec de récupération individuel
  est ignoré (l'offre n'est ni comptée ni persistée).
"""

import hashlib
from dataclasses import dataclass
from typing import List, Tuple
from urllib.parse import urlparse

from config.logger_config import setup_logging
from src.core.domain.job_offer import JobOffer
from src.core.scoring.url_offer_extractor import (
    LIST_MAX_URLS,
    MAX_PAGE_CHARS,
    LLMExtractionError,
    URLScrapingError,
    extract_offer,
    extract_page,
)
from src.infrastructure.db.repositories import job_offer_repository
from src.infrastructure.db.session import session_scope
from src.interfaces.scrapers.url.scraper import URLScraper, normalize_url
from src.services.job_parser import normalize_job_offer

logger = setup_logging(__name__)

# Bornes du nombre maximal d'offres **nouvelles** à ingérer pour une liste
# (alignées sur le contrat API : slider 1 → 20, défaut 5).
MAX_OFFERS_MIN = 1
MAX_OFFERS_MAX = 20
DEFAULT_MAX_OFFERS = 5

# Nombre d'URLs d'une liste à demander au LLM : marge sur ``max_offers`` (il
# faut assez d'URLs pour compenser celles déjà en base, ignorées avant la
# récupération individuelle). Plancher ``LIST_MAX_URLS_FLOOR`` (robustesse face
# au dédoublonnage), plafonné à ``LIST_MAX_URLS`` (borne du prompt / défense
# serveur). Borner la demande est crucial sur les pages aux URLs longues (ex.
# Indeed, tracking ``pagead/clk`` de ~350-500 caractères) : 50 URLs ≈ 18 k
# caractères de sortie LLM, au-delà du budget de tokens d'extraction.
LIST_MAX_URLS_FLOOR = 10
LIST_MAX_URLS_MULTIPLIER = 2

# Taille maximale du « source » collé (champ ``source`` de
# POST /job-offers/from-url) : corps d'API non borné sinon. Généreux car un
# « afficher le code source » embarque styles + JavaScript (bruit retiré
# ensuite par ``_source_to_text``/``_html_to_text``) ; le **vrai** budget est
# ``MAX_PAGE_CHARS`` (12 000) appliqué à la conversion : quel que soit le HTML
# brut, le LLM ne voit que le texte utile, tronqué. Ce garde-fou ne borne que
# la taille du corps HTTP (la route refuse au-delà : HTTP 413).
SOURCE_MAX_CHARS = 2_000_000


class URLOfferDuplicateError(RuntimeError):
    """L'URL est déjà présente en base (page d'offre unique). → HTTP 409."""


@dataclass
class URLIngestResult:
    """Résultat de l'ingestion : clés de dédoublonnage des offres persistées et
    compteurs, consommés par la route pour refetch et réponse.

    ``keys`` : paires ``(source, source_job_id)`` des offres effectivement
    persistées — une seule pour une offre unique, plusieurs (éventuellement de
    domaines différents) pour une liste. ``added`` : offres nouvellement
    insérées. ``already_present`` : nombre d'offres déjà en base — pour une
    liste, les URLs déjà présentes (ignorées sans mise à jour) ; une offre
    unique doublon lève 409 avant tout retour (``already_present == 0``).
    """

    keys: List[Tuple[str, str]]
    added: int
    already_present: int


class URLJobIngestorService:
    """Orchestre l'ingestion d'offres depuis une URL (offre unique ou liste)."""

    def __init__(self, scraper: URLScraper | None = None):
        self.scraper = scraper or URLScraper()

    def _urls_to_request(self, max_offers: int) -> int:
        """Nombre d'URLs d'une liste à demander au LLM (borné au besoin).

        ``max_offers`` est le nombre d'offres **nouvelles** souhaitées : on
        demande une marge (``LIST_MAX_URLS_MULTIPLIER`` ×, plancher
        ``LIST_MAX_URLS_FLOOR``) car certaines URLs sont déjà en base et
        ignorées sans fetch. Plafonné à ``LIST_MAX_URLS``.
        """
        return min(
            LIST_MAX_URLS,
            max(LIST_MAX_URLS_FLOOR, int(max_offers) * LIST_MAX_URLS_MULTIPLIER),
        )

    def run(self, url: str, max_offers: int = DEFAULT_MAX_OFFERS) -> URLIngestResult:
        """Ingère les offres d'une URL (une seule ou une liste) et retourne le résultat.

        Pour une liste, ``max_offers`` est le nombre maximal d'offres
        **nouvelles** (non déjà en base) à ingérer, dans l'ordre de la page.

        Args:
            url: URL de la page (offre unique ou liste d'offres).
            max_offers: nombre maximal d'offres nouvelles à ingérer (borné à
                [1, 20]).

        Raises:
            URLOfferDuplicateError: page d'offre unique déjà en base (ou insérée
                entre le contrôle et l'upsert — course TOCTOU).
            URLScrapingError: URL invalide, fetch en échec ou page sans offre
                exploitable.
            LLMExtractionError: LLM d'extraction indisponible.
        """
        url = normalize_url(url)
        max_offers = max(MAX_OFFERS_MIN, min(int(max_offers), MAX_OFFERS_MAX))
        logger.info(
            "Ingestion d'offres depuis l'URL: %s (max nouvelles=%d)", url, max_offers
        )

        page_text = self.scraper.fetch_text(url)
        # Le nombre d'URLs demandées au LLM est borné au besoin (marge sur
        # ``max_offers``), pas à ``LIST_MAX_URLS`` : sur une page aux URLs
        # longues (ex. Indeed), la sortie du LLM reste sous le budget de tokens.
        page = extract_page(page_text, max_urls=self._urls_to_request(max_offers))

        if page.page_type == "single":
            return self._ingest_single(url, page.offer)
        return self._ingest_list(page.urls, max_offers)

    def run_from_source(self, url: str, source_text: str) -> URLIngestResult:
        """Ingère une offre unique depuis le contenu de sa page, collé par
        l'utilisateur (champ ``source`` de ``POST /job-offers/from-url``).

        Remplace le fetch Playwright par le texte fourni : le contenu (HTML du
        code source de la page, ou texte déjà brut) est converti en texte
        exploitable puis extrait par le LLM (``extract_offer``, **mono-offre**
        obligatoire) et ingéré via le chemin offre unique (``_ingest_single``).

        L'URL soumise est la clé de dédoublonnage (409 si déjà en base, source =
        domaine) mais **n'est jamais récupérée** : c'est l'utilisateur qui
        fournit le contenu, ce qui débloque les sites dont la page bloque le
        navigateur headless (anti-bot) sans implémenter de contournement
        automatisé. Un source de page de recherche (liste) répond 422 — seul le
        contenu d'une offre unique est accepté.

        Raises:
            URLOfferDuplicateError: l'URL est déjà en base.
            URLScrapingError: URL invalide ou source collé sans offre unique
                exploitable.
            LLMExtractionError: LLM d'extraction indisponible.
        """
        url = normalize_url(url)
        page_text = self._source_to_text(source_text, url)
        offer = extract_offer(page_text)
        return self._ingest_single(url, offer)

    @staticmethod
    def _source_to_text(source_text: str, base_url: str) -> str:
        """Convertit le source collé en texte exploitable par le LLM d'extraction.

        HTML (code source de navigateur, ex. « Afficher le code source ») →
        même conversion que le fetch Playwright (``URLScraper._html_to_text`` :
        structure des blocs préservée, scripts/styles retirés) ; texte déjà
        brut → tel quel. Borné à ``MAX_PAGE_CHARS`` comme le chemin URL.
        """
        head = source_text.lstrip()[:1000].lower()
        if (
            head.startswith("<html")
            or head.startswith("<!doctype")
            or "<body" in head
        ):
            return URLScraper._html_to_text(source_text, base_url=base_url)
        return source_text[:MAX_PAGE_CHARS]

    def _ingest_single(self, url: str, offer: dict) -> URLIngestResult:
        """Chemin « offre unique » : la page EST l'offre (comportement historique).

        L'URL soumise est la clé de dédoublonnage : 409 si déjà en base. Le
        contenu est déjà extrait par ``extract_page`` — aucun fetch supplémentaire.
        """
        with session_scope() as session:
            existing = job_offer_repository.get_by_url(session, url)
            if existing is not None:
                logger.info("Offre déjà en base (id=%s) : %s", existing.id, url)
                raise URLOfferDuplicateError(
                    f"Cette offre est déjà en base (id={existing.id})"
                )

        source = urlparse(url).netloc.lower()
        row = normalize_job_offer(self._build_job_offer(url, source, offer))
        with session_scope() as session:
            ingested, _, _ = job_offer_repository.upsert_many(session, [row])
            if ingested == 0:
                # Course TOCTOU : inséré entre le contrôle et l'upsert
                # (ON CONFLICT DO NOTHING) → traité comme doublon.
                raise URLOfferDuplicateError("Cette offre est déjà en base")

        return URLIngestResult(
            keys=[(row["source"], row["source_job_id"])],
            added=ingested,
            already_present=0,
        )

    def _ingest_list(self, urls: List[str], max_offers: int) -> URLIngestResult:
        """Chemin « liste d'offres » : récupération individuelle des URLs nouvelles.

        Le LLM a extrait les URLs des offres de la liste (dans l'ordre de la
        page). On écarte celles déjà en base (colonne ``url``, indépendamment de
        la source — elles ne sont **pas** mises à jour, leur contenu n'étant pas
        récupéré), puis on récupère chacune des ``max_offers`` premières URLs
        nouvelles (fetch Playwright + extraction mono-offre) et on upsert. Un
        échec de récupération individuel (page indisponible, URL refusée par la
        barrière SSRF, extraction impossible) est ignoré : l'offre n'est ni
        comptée ni persistée, et ``added`` peut être < ``max_offers``.
        """
        # Dédoublonnage des URLs renvoyées par le LLM (ordre préservé) : une
        # même URL ne doit être ni comptée ni fetchée deux fois — un doublon
        # consommerait inutilement un slot de ``max_offers`` (fetch Playwright
        # + extraction LLM) et gonflerait ``already_present``.
        urls = list(dict.fromkeys(urls))
        with session_scope() as session:
            existing = job_offer_repository.existing_urls(session, urls)

        available = [u for u in urls if u not in existing]
        already_present = len(urls) - len(available)
        new_urls = available[:max_offers]

        # Collecte de toutes les offres avant un seul upsert batché.
        rows: List[Dict] = []
        for offer_url in new_urls:
            try:
                offer_text = self.scraper.fetch_text(offer_url)
                offer = extract_offer(offer_text)
            except (URLScrapingError, LLMExtractionError) as exc:
                logger.warning("Offre individuelle ignorée (%s) : %s", offer_url, exc)
                continue
            source = urlparse(offer_url).netloc.lower()
            rows.append(normalize_job_offer(self._build_job_offer(offer_url, source, offer)))

        # Un seul upsert batché pour toutes les offres collectées.
        keys: List[Tuple[str, str]] = []
        added = 0
        if rows:
            with session_scope() as session:
                ingested, _, _ = job_offer_repository.upsert_many(session, rows)
                added = ingested
                keys = [(r["source"], r["source_job_id"]) for r in rows]

        return URLIngestResult(keys=keys, added=added, already_present=already_present)

    def _build_job_offer(self, url: str, source: str, offer: dict) -> JobOffer:
        """Construit un ``JobOffer`` depuis une offre extraite.

        Chaque offre a sa propre URL réelle (l'URL soumise pour une offre
        unique, l'URL individuelle pour une liste) : elle est la clé de
        dédoublonnage ``source_job_id = sha256(url)``.
        """
        offer_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return JobOffer(
            id=offer_id,  # → source_job_id (clé de dédoublonnage unique)
            source=source,  # nom de domaine de l'URL de l'offre
            url=url,
            time_posted="",
            contract_type=offer.get("contract_type") or "",
            title=offer.get("title") or "",
            company=offer.get("company") or "",
            localisation=offer.get("location") or "",
            description=offer.get("description"),
            # Doit rester une chaîne : _compute_content_hash sérialise sans
            # ``default=str`` et raw_payload (JSONB) n'accepte pas les date.
            published_date=offer.get("published_date") or None,
            experience=offer.get("experience") or "",
            diploma=offer.get("diploma") or [],
        )
