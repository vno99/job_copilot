import json
import random
import re
import time
from itertools import product
from pathlib import Path
from urllib.parse import urlencode

import requests
from lxml import etree
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config.logger_config import setup_logging
from src.config.settings import KEYWORD_LIST, LOCATION_LIST
from src.core.domain.job_offer import JobOffer
from src.core.html_text import element_to_text

logger = setup_logging(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/53_6_applewebkit",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]

TIMEOUT = 5

# KEYWORD_LIST = ["data engineer", "snowflake", "dbt", "data scientist"]
# KEYWORD_LIST = ["data engineer"]
# LOCATION_LIST = ["Île-de-France"]  # %C3%8Ele-de-France

BASE_URL = "https://www.hellowork.com"
API_HOST = f"{BASE_URL}/fr-fr/emploi/recherche.html"

SOURCE = "hellowork"

XPATH_QUERY = "//ul[@aria-label='liste des offres']/li"
XPATH_ID = "./@data-id-storage-item-id"
XPATH_TITLE = ".//a[@data-cy='offerTitle']/p[1]/text()"
XPATH_COMPANY = ".//a[@data-cy='offerTitle']/p[2]/text()"
XPATH_URL = ".//a[@data-cy='offerTitle']/@href"
XPATH_LOCALISATION = ".//div[@data-cy='localisationCard']/text()"
XPATH_CONTRACT_TYPE = ".//div[@data-cy='contractCard']/text()"
XPATH_CONTRACT_LENGTH = ".//div[@data-cy='contractTag']/text()"
XPATH_TIME_POSTED = ".//div[contains(@class, 'text-grey-500')]/text()"
XPATH_DESCR = "//div[@id='offer-panel']/div[contains(@class, 'flex flex-col gap-8')]/div[1]"
XPATH_PUBLISHED_DATE = "//div[@id='offer-panel']/*[last()]"
# Badges du header de la page de détail : diplômes, expérience requise, secteur…
XPATH_BADGES = "//div[@id='offer-panel']//li"
# Société affichée dans le header de la page de détail (sous le titre)
XPATH_COMPANY_DETAIL = "//h1//p/text()"

OUTPUT_DIR = Path("./data/hellowork/")

EXCLUDE_CONTRACT_TYPE = ["Stage", "Alternance"]


def _xpath_text(element, xpath: str, default: str = "") -> str:
    """Premier texte non vide correspondant à un xpath, sinon ``default``.

    Évite qu'une liste vide retournée par lxml (xpath sans correspondance)
    ne soit propagée telle quelle dans les objets métier.
    """
    results = element.xpath(xpath)
    if not results:
        return default
    first = results[0]
    text = first.strip() if isinstance(first, str) else " ".join(first.itertext()).strip()
    return text or default


class HelloworkOneJobOfferParser:

    def __init__(self, html_content: str, job: JobOffer):
        self.tree = etree.HTML(html_content)
        self.job = job

    def extract_announcement_details(self, job: JobOffer) -> JobOffer:
        """Extracts detailed information from a single job.

        Args:
            job (JobOffer): The `JobOffer` object to be updated with extracted data.

        Returns:
            JobOffer: The updated `JobOffer` object
        """
        try:
            desc_elements = self.tree.xpath(XPATH_DESCR)

            description = ""
            if desc_elements:
                # ``element_to_text`` préserve la structure du bloc de
                # description (paragraphes, listes à puces) : un simple
                # ``" ".join(el.itertext())`` aplatirait l'offre en un seul
                # paragraphe compact.
                description = element_to_text(desc_elements[0])
                job.description = description


            published_date_elements = self.tree.xpath(XPATH_PUBLISHED_DATE)
            if published_date_elements:

                published_date = [
                    " ".join(el.itertext()).strip() for el in published_date_elements
                ][0]
                match = re.search(r"\d{2}/\d{2}/\d{4}", published_date)

                if match:
                    published_date = match.group(0)
                    job.published_date = published_date

            # Diplômes et expérience requise : badges du header de l'annonce
            badge_elements = self.tree.xpath(XPATH_BADGES)

            experience = ""
            diploma = []
            for badge in badge_elements:
                text = " ".join(badge.itertext()).strip()
                if "Bac" in text:
                    diploma.append(text)
                elif "Exp." in text:
                    experience = text
                else:
                    continue
            job.diploma = ", ".join(diploma)
            job.experience = experience

            # Société absente de la liste de recherche : récupérée depuis la page
            if not job.company:
                company_detail = self.tree.xpath(XPATH_COMPANY_DETAIL)
                if company_detail and company_detail[0].strip():
                    job.company = company_detail[0].strip()

            logger.info(f"Job traité avec succès: {job.id}")

        except Exception as e:
            logger.error(
                f"Erreur lors du traitement du job {job.id} (URL: {job.url}): {str(e)}"
            )

        return job


class HelloworkJobOffersListParser:

    def __init__(self, html_content: str, base_url: str):
        self.tree = etree.HTML(html_content)
        self.base_url = base_url

    def parse_job_offers_list(self) -> list[JobOffer]:
        """Extracts a list of job announcements from search results.

        Returns:
            list[JobOffer]: A list of `JobOffer` objects.
        """
        jobs_list = []
        items = self.tree.xpath(XPATH_QUERY)  # Placeholder XPATH

        NB_MAX = 5

        if items:

            for index, item in enumerate(items):
                job_id = _xpath_text(item, XPATH_ID)

                time_posted = _xpath_text(item, XPATH_TIME_POSTED)

                if index > NB_MAX:
                    logger.info(
                        f"Arrêt de la liste : NB_MAX atteint: {NB_MAX}"
                    )
                    break

                # on ne garde que les jobs < 1 jour : on s'arrête dès qu'une
                # annonce est postée il y a ≥ 1 jour ("il y a 1 jour",
                # "il y a 5 jours"). "Aujourd'hui" (posté ce jour) et "Hier"
                # sont conservés — ne pas tester la sous-chaîne "jour",
                # présente aussi dans "Aujourd'hui".
                if re.search(r"\d+\s*jours?\b", time_posted, flags=re.IGNORECASE):
                    logger.info(
                        f"Arrêt de la liste : job trop ancien ({time_posted})"
                    )
                    break

                contract_type = _xpath_text(item, XPATH_CONTRACT_TYPE)

                # on exclut les contrats de la liste EXCLUDE_CONTRACT_TYPE
                if contract_type in EXCLUDE_CONTRACT_TYPE:
                    logger.debug(
                        f"Job {job_id} ignoré : type de contrat '{contract_type}' exclu."
                    )
                    continue

                title = _xpath_text(item, XPATH_TITLE)
                company = _xpath_text(item, XPATH_COMPANY)

                url = _xpath_text(item, XPATH_URL)
                if url:
                    url = f"{BASE_URL}{url}"

                localisation = _xpath_text(item, XPATH_LOCALISATION)
                contract_length = _xpath_text(item, XPATH_CONTRACT_LENGTH)

                a_job = JobOffer(
                    job_id,
                    SOURCE,
                    url,
                    time_posted,
                    contract_type,
                    title,
                    company,
                    localisation,
                    contract_length,
                )

                jobs_list.append(a_job)

                logger.debug(f"Job ajouté à la liste: {title} ({job_id})")

        return jobs_list


class HelloworkScraper:

    def __init__(self, max_retries: int = 3, backoff_factor: float = 2.0):
        self.session = requests.Session()
        self.user_agent = random.choice(USER_AGENTS)

        self.headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.hellowork.com/",
        }

        self.session.headers.update(self.headers)
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def fetch_html(self, url: str) -> str | None:
        """Fetches HTML content from a given URL with retry logic.

        Args:
            url (str): The URL of the web page to fetch.

        Returns:
            str: The raw HTML content of the response if the request succeeds.
            None: Returns `None` if the request fails after all retry attempts.
                This allows the caller to handle the failure gracefully (e.g., skip the page).
        """
        time.sleep(random.uniform(2, 5))

        logger.info(f"Traitement de l'url: {url}")

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=TIMEOUT,
                )
                response.raise_for_status()

                return response.text

            except requests.RequestException as e:
                if attempt < self.max_retries:
                    sleep_time = self.backoff_factor**attempt
                    logger.warning(
                        f"Tentative {attempt + 1}/{self.max_retries + 1} échouée pour {url}. "
                        f"Réessai dans {sleep_time}s... (Erreur: {e})"
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        f"Échec définitif après {self.max_retries + 1} tentatives pour {url}: {e}"
                    )
                    return None

    def fetch_html_with_playwright(self, url: str) -> str | None:
        logger.info(f"Traitement de l'url: {url}")

        for attempt in range(self.max_retries + 1):
            browser = None

            try:
                with sync_playwright() as p:
                    # Lancer un navigateur avec des options pour ressembler à un humain
                    browser = p.chromium.launch(
                        headless=True,  # Mettre à True en production
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--disable-dev-shm-usage',
                            '--no-sandbox',
                            '--disable-web-security',
                            '--disable-features=IsolateOrigins,site-per-process',
                            '--disable-gpu',  # Utile en conteneur
                            '--window-size=1920,1080',
                        ]
                    )
                    
                    context = browser.new_context(
                        user_agent=random.choice(USER_AGENTS),
                        viewport={'width': random.randint(1024, 1920), 'height': random.randint(768, 1080)},
                        locale='fr-FR',
                        timezone_id='Europe/Paris',
                        permissions=['geolocation'],
                        java_script_enabled=True,
                    )
                    
                    page = context.new_page()

                    time.sleep(random.uniform(1, 3))

                    # Naviguer vers l'URL avec un timeout
                    try:
                        response = page.goto(url, wait_until='networkidle', timeout=20000)
                    except PlaywrightTimeoutError:
                        logger.warning(f"Timeout lors du chargement de {url}, tentative {attempt + 1}")
                        continue

                    # Vérifier le statut de la réponse
                    if response and response.status >= 400:
                        logger.warning(f"HTTP {response.status} pour {url}")

                        if response.status == 403:
                            # 403 = Forbidden, changer d'IP ou de user-agent
                            logger.warning("403 Forbidden détecté, changement de user-agent pour la prochaine tentative")
                            self.session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                        continue

                    # Attendre que le contenu soit chargé
                    page.wait_for_load_state('networkidle', timeout=10000)
                    
                    # Petit délai supplémentaire pour laisser le JavaScript s'exécuter
                    time.sleep(random.uniform(0.5, 2))
                    
                    # Récupérer le HTML complet après exécution JS
                    html = page.content()

                    # Vérifier que le HTML n'est pas vide
                    if not html or len(html) < 100:
                        logger.warning(f"HTML trop court ({len(html)} caractères) pour {url}")
                        continue
                    
                    logger.info(f"HTML récupéré avec succès ({len(html)} caractères)")

                    return html
                
            except PlaywrightTimeoutError as e:
                logger.warning(f"Timeout Playwright, tentative {attempt + 1}: {e}")
                
            except Exception as e:
                logger.error(f"Erreur inattendue, tentative {attempt + 1}: {e}")

            finally:
                # Toujours fermer le navigateur proprement
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass

            # Gestion des retries
            if attempt < self.max_retries:
                sleep_time = self.backoff_factor ** attempt * random.uniform(0.8, 1.2)
                logger.info(f"Attente de {sleep_time:.2f}s avant la tentative {attempt + 2}")
                time.sleep(sleep_time)
        
        logger.error(f"Échec définitif après {self.max_retries + 1} tentatives pour {url}")
        return None



class HelloworkService:

    def __init__(self):
        self.scraper = HelloworkScraper()
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_search_urls(
        self, base_url: str, keyword_list: list[str], location_list: list[str]
    ) -> list[str]:
        """Generates a list of search URLs based on keyword and location combinations.

        Args:
            base_url (str): The base URL of the search API. The final URLs will be constructed by appending
                query parameters to this base.
            keyword_list (list[str]): A list of job keywords or titles to search for
                (e.g., ['developer', 'designer', 'manager']).
            location_list (list[str]): A list of location names to search
                in (e.g., ['Paris', 'Lyon']).

        Returns:
            list[str]: A list of absolute URLs, one for each unique combination of
                keyword and location. The list length will be `len(keyword_list) *
                len(location_list)`.
        """
        url_list = []

        for keyword, location in product(keyword_list, location_list):
            params = {
                "k": keyword,
                "k_autocomplete": "",
                "l": location,
                "st": "date",
                "msa": 0,
                "ray": 20,
                "d": "all",
            }

            api_url = f"{base_url}?{urlencode(params)}"

            url_list.append(api_url)

        return url_list

    def process_search_results(self, search_url: str) -> list[JobOffer]:
        """Fetches and parses search results from a given URL.

        Args:
            search_url (str): The absolute URL of the search results page to scrape.

        Returns:
            list[JobOffer]: A list of `JobOffer` objects.
        """
        html = self.scraper.fetch_html_with_playwright(search_url)
        if not html:
            return []

        parser = HelloworkJobOffersListParser(html, search_url)

        return parser.parse_job_offers_list()

    def scrape_job_details(self, job: JobOffer) -> JobOffer | None:
        """Fetches and extracts detailed information from a specific job posting.

        Args:
            job (JobOffer): The `JobOffer` object representing the job posting.

        Returns:
            JobOffer | None: The updated `JobOffer` object containing the detailed
                information if the page is successfully scraped.
            None: Returns `None` if the request to fetch the detail page fails
                (e.g., network error, 404 Not Found) or if parsing fails.
        """
        html = self.scraper.fetch_html_with_playwright(job.url)
        if not html:
            return None

        parser = HelloworkOneJobOfferParser(html, job)

        return parser.extract_announcement_details(job)

    def save_to_json(self, job: JobOffer) -> None:
        """Saves the details of a single job posting to a JSON file.

        Args:
            job (JobOffer): The `JobOffer` object to serialize.
        """

        filename = f"{OUTPUT_DIR}/{job.id}.json"
        if Path(filename).exists():
            logger.debug(f"Job {job.id} déjà traitée, sautée.")
            return None

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(job.to_dict(), f, indent=4, ensure_ascii=False)

    def run(self, keyword_list, location_list, known_urls: set[str] | None = None):
        """Executes the main scraping workflow.

        Args:
            keyword_list (list[str]): A list of job keywords or titles to search for
                (e.g., ['developer', 'designer']).
            location_list (list[str]): A list of location names to search
                in (e.g., ['Paris', 'Lyon']).
            known_urls (set[str] | None): URLs déjà présentes en base. Les annonces
                correspondantes sont ignorées avant le scrape des détails, pour
                ne pas re-scraper une offre déjà connue.
        """
        logger.info("Début du scrapping")

        known_urls = known_urls or set()
        url_list = self.get_search_urls(API_HOST, keyword_list, location_list)

        for url in url_list:
            logger.info(f"Traitement de la recherche: {url}")

            jobs_list = self.process_search_results(url)

            for job in jobs_list:
                if job.url in known_urls:
                    logger.info(f"Job {job.id} déjà en base (URL connue), sautée.")
                    continue

                try:
                    logger.info(f"Traitement du job: {job.id}")

                    detail = self.scrape_job_details(job)
                    if detail is None:
                        # Détail indisponible (fetch du détail en échec) : ne pas
                        # persister une offre partielle — elle sera retentée au
                        # prochain run.
                        logger.warning(
                            f"Job {job.id} : détail indisponible, non persisté "
                            "(retenté au prochain run)."
                        )
                        continue
                    self.save_to_json(job)

                except Exception as e:
                    logger.error(f"Erreur sur le job {job.id}: {e}")
                    continue

        logger.info("Fin du scraping")


if __name__ == "__main__":
    service = HelloworkService()
    service.run(KEYWORD_LIST, LOCATION_LIST)
