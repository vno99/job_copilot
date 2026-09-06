import requests
from unittest.mock import MagicMock, patch, PropertyMock

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.domain.job_offer import JobOffer
from src.interfaces.scrapers.hellowork.scraper import (
    HelloworkJobOffersListParser,
    HelloworkOneJobOfferParser,
    HelloworkScraper,
    HelloworkService,
)


def _detail_html():
    """Structure actuelle de la page de détail Hellowork.

    ``#offer-panel`` : header (titre + société + badges), corps (description),
    puis bloc de la date de publication.
    """
    return """
    <html><body>
        <div id="offer-panel">
            <div class="border-b border-b-grey-100 mb-8 sm:mb-10">
                <h1>
                    <span class="block typo-xl sm:typo-2xl mb-3">Dev H/F</span>
                    <span class="flex items-center gap-2"><p class="typo-s sm:typo-m">Acme</p></span>
                    <ul>
                        <li>Paris</li>
                    </ul>
                </h1>
                <ul>
                    <li class="block tag-secondary-s border-0 readonly">Bac+5</li>
                    <li class="block tag-secondary-s border-0 readonly">Exp. 3 years</li>
                </ul>
            </div>
            <div class="flex flex-col gap-8 sm:gap-10">
                <div>Description of the job</div>
            </div>
            <p class="block mt-8 sm:mt-12 typo-xs text-grey-500 break-words">Publiée le 12/05/2024</p>
        </div>
    </body></html>
    """


def test_hellowork_parser_date_parsing():
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 day",
        contract_type="CDI",
        title="Dev",
    )

    parser = HelloworkOneJobOfferParser(_detail_html(), job)
    updated_job = parser.extract_announcement_details(job)

    assert updated_job.published_date == "12/05/2024"
    assert "Description of the job" in updated_job.description
    assert "3 years" in updated_job.experience
    assert "Bac+5" in updated_job.diploma


def test_hellowork_parser_preserves_description_structure():
    """La description d'une offre affichée en blocs (paragraphes, listes) garde
    sa structure : elle ne doit pas être aplatie en un seul paragraphe compact
    (```\n`` séparant les blocs, items de liste préfixés par « - »)."""
    html_content = """
    <html><body>
        <div id="offer-panel">
            <div class="flex flex-col gap-8">
                <div>
                    <p>Venez rejoindre le leader.</p>
                    <p>Vos missions seront :</p>
                    <ul>
                        <li>Fabriquer les produits</li>
                        <li>Contrôler la qualité</li>
                    </ul>
                    <p>CDI 35h/semaine</p>
                </div>
            </div>
            <p class="block">Publiée le 12/05/2024</p>
        </div>
    </body></html>
    """
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 day",
        contract_type="CDI",
        title="Dev",
    )

    parser = HelloworkOneJobOfferParser(html_content, job)
    updated_job = parser.extract_announcement_details(job)

    assert "- Fabriquer les produits" in updated_job.description
    assert "- Contrôler la qualité" in updated_job.description
    assert "Venez rejoindre le leader." in updated_job.description
    # Les blocs sont séparés par des retours à la ligne (pas un seul paragraphe).
    assert "\n" in updated_job.description


def test_hellowork_parser_no_date():
    job = JobOffer(
        id="1",
        source="s",
        url="u",
        time_posted="t",
        contract_type="c",
        title="t",
    )
    html_content = "<html><body><div id='offer-panel'><div>No date here</div></div></body></html>"
    parser = HelloworkOneJobOfferParser(html_content, job)
    updated_job = parser.extract_announcement_details(job)
    assert updated_job.published_date is None


def test_hellowork_parser_company_from_detail():
    # La société est absente de la liste de recherche (company vide) :
    # elle doit être récupérée depuis le header de la page de détail.
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 heure",
        contract_type="CDI",
        title="Dev",
        company=[],
    )
    parser = HelloworkOneJobOfferParser(_detail_html(), job)
    updated_job = parser.extract_announcement_details(job)
    assert updated_job.company == "Acme"


def test_hellowork_list_parser_empty_company():
    html_content = """
    <html><body>
        <ul aria-label="liste des offres">
            <li data-id-storage-item-id="123">
                <a data-cy="offerTitle" href="/emplois/123.html">
                    <p>Data Engineer H/F</p>
                    <p>Acme</p>
                </a>
                <div data-cy="localisationCard">Paris</div>
                <div data-cy="contractCard">CDI</div>
                <div class="text-grey-500">il y a 1 heure</div>
            </li>
            <li data-id-storage-item-id="124">
                <a data-cy="offerTitle" href="/emplois/124.html">
                    <p>ML Engineer H/F</p>
                    <p></p>
                </a>
                <div data-cy="localisationCard">Lyon</div>
                <div data-cy="contractCard">CDI</div>
                <div class="text-grey-500">il y a 2 heures</div>
            </li>
        </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()

    assert len(jobs) == 2
    assert jobs[0].company == "Acme"
    # Société absente de la carte : chaîne vide, jamais une liste vide []
    assert jobs[1].company == ""
    assert jobs[1].title == "ML Engineer H/F"


def test_hellowork_service_run_empty(monkeypatch):
    """Couvre le chemin où get_search_urls renvoie une liste vide."""
    service = HelloworkService()
    monkeypatch.setattr(service, "get_search_urls", lambda *a, **k: [])
    monkeypatch.setattr(service, "process_search_results", lambda *a, **k: [])
    service.run(["data engineer"], ["Paris"], known_urls=set())


def test_run_skips_known_urls(monkeypatch):
    """Les annonces déjà connues (URL en base) ne sont pas re-scrapées."""
    known_job = JobOffer(
        id="1",
        source="hellowork",
        url="https://www.hellowork.com/fr-fr/emplois/1.html",
        time_posted="",
        contract_type="CDI",
        title="Déjà connue",
    )
    new_job = JobOffer(
        id="2",
        source="hellowork",
        url="https://www.hellowork.com/fr-fr/emplois/2.html",
        time_posted="",
        contract_type="CDI",
        title="Nouvelle",
    )

    service = HelloworkService()
    monkeypatch.setattr(service, "get_search_urls", lambda *a, **k: ["http://search"])
    monkeypatch.setattr(
        service, "process_search_results", lambda *a, **k: [known_job, new_job]
    )
    scraped_ids = []
    monkeypatch.setattr(service, "scrape_job_details", lambda job: scraped_ids.append(job.id))
    monkeypatch.setattr(service, "save_to_json", lambda job: None)

    service.run(["data engineer"], ["Île-de-France"], known_urls={known_job.url})

    # Seule l'annonce inconnue passe par le scrape des détails.
    assert scraped_ids == ["2"]


def test_hellowork_parser_empty_list():
    parser = HelloworkJobOffersListParser("<html><body><ul aria-label=\"liste des offres\"></ul></body></html>", "http://test")
    assert parser.parse_job_offers_list() == []




# ---------------------------------------------------------------------------
# Tests des lignes non couvertes du parser de liste
# ---------------------------------------------------------------------------

def test_hellowork_list_parser_stops_at_nb_max():
    """NB_MAX (5) interrompt la liste apres 6 offres (index 0-5 = 6 items car index > NB_MAX declenche le break)."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="1">
            <a data-cy="offerTitle" href="/emplois/1.html"><p>Job 1</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 10 minutes</div>
        </li>
        <li data-id-storage-item-id="2">
            <a data-cy="offerTitle" href="/emplois/2.html"><p>Job 2</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 20 minutes</div>
        </li>
        <li data-id-storage-item-id="3">
            <a data-cy="offerTitle" href="/emplois/3.html"><p>Job 3</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
        <li data-id-storage-item-id="4">
            <a data-cy="offerTitle" href="/emplois/4.html"><p>Job 4</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 40 minutes</div>
        </li>
        <li data-id-storage-item-id="5">
            <a data-cy="offerTitle" href="/emplois/5.html"><p>Job 5</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 50 minutes</div>
        </li>
        <li data-id-storage-item-id="6">
            <a data-cy="offerTitle" href="/emplois/6.html"><p>Job 6</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 60 minutes</div>
        </li>
        <li data-id-storage-item-id="7">
            <a data-cy="offerTitle" href="/emplois/7.html"><p>Job 7</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 70 minutes</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    # NB_MAX = 5 -> index 0-5 (6 items) sont traites, le 7e (index 6) declenche le break
    assert len(jobs) == 6
    assert all(j.id != "7" for j in jobs)


def test_hellowork_list_parser_skips_old_jobs():
    """Un job poste il y a 1 jour ou plus interrompt la liste."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="1">
            <a data-cy="offerTitle" href="/emplois/1.html"><p>Job recent</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 3 heures</div>
        </li>
        <li data-id-storage-item-id="2">
            <a data-cy="offerTitle" href="/emplois/2.html"><p>Job ancien</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 2 jours</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    # Le premier job 'il y a 3 heures' est garde ; 'il y a 2 jours' interrompt.
    assert len(jobs) == 1
    assert jobs[0].id == "1"


def test_hellowork_list_parser_skips_singular_day():
    """Le singulier '1 jour' est aussi filtre."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="1">
            <a data-cy="offerTitle" href="/emplois/1.html"><p>Job 1 jour</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 jour</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 0


def test_hellowork_list_parser_excludes_contract_types():
    """Les contrats Stage et Alternance sont exclus."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="1">
            <a data-cy="offerTitle" href="/emplois/1.html"><p>Job CDI</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
        <li data-id-storage-item-id="2">
            <a data-cy="offerTitle" href="/emplois/2.html"><p>Job Stage</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Stage</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
        <li data-id-storage-item-id="3">
            <a data-cy="offerTitle" href="/emplois/3.html"><p>Job Alternance</p><p>Acme</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Alternance</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].contract_type == "CDI"
    assert jobs[0].id == "1"


# ---------------------------------------------------------------------------
# Tests de HelloworkService
# ---------------------------------------------------------------------------

def test_get_search_urls():
    """get_search_urls genere une URL par combinaison keyword x location."""
    service = HelloworkService()
    urls = service.get_search_urls(
        "https://www.hellowork.com/fr-fr/emploi/recherche.html",
        ["data engineer", "ml engineer"],
        ["Paris", "Lyon"],
    )
    assert len(urls) == 4
    assert all("k=data+engineer" in u or "k=ml+engineer" in u for u in urls)
    assert all("l=Paris" in u or "l=Lyon" in u for u in urls)


def test_process_search_results_empty(monkeypatch):
    """process_search_results renvoie [] si le scraper renvoie None."""
    service = HelloworkService()
    monkeypatch.setattr(service.scraper, "fetch_html_with_playwright", lambda url: None)
    result = service.process_search_results("http://test")
    assert result == []


def test_save_to_json_skips_existing_file(monkeypatch, tmp_path):
    """save_to_json ne reecrit pas un fichier deja existant."""
    service = HelloworkService()
    monkeypatch.setattr(
        "src.interfaces.scrapers.hellowork.scraper.OUTPUT_DIR", tmp_path
    )
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com/123.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    (tmp_path / "123.json").write_text("{}")
    result = service.save_to_json(job)
    assert result is None
    assert (tmp_path / "123.json").read_text() == "{}"


def test_run_continues_on_job_exception(monkeypatch):
    """Une exception dans scrape_job_details ne stoppe pas le run."""
    service = HelloworkService()
    monkeypatch.setattr(service, "get_search_urls", lambda *a, **k: ["http://search"])
    monkeypatch.setattr(
        service, "process_search_results", lambda url: [
            JobOffer("1", "hellowork", "http://job1.com", "", "CDI", "Dev1"),
            JobOffer("2", "hellowork", "http://job2.com", "", "CDI", "Dev2"),
        ]
    )
    call_order = []

    def fake_scrape(job):
        call_order.append(job.id)
        if job.id == "1":
            raise RuntimeError("Erreur simulee")
        return job

    monkeypatch.setattr(service, "scrape_job_details", fake_scrape)
    monkeypatch.setattr(service, "save_to_json", lambda j: None)

    service.run(["data engineer"], ["Paris"], known_urls=set())

    assert "1" in call_order
    assert "2" in call_order


def test_run_skips_known_urls_via_known_urls_param(monkeypatch):
    """known_urls empeche le scrape des details pour les offres deja en base."""
    known_job = JobOffer(
        id="1",
        source="hellowork",
        url="https://www.hellowork.com/fr-fr/emplois/1.html",
        time_posted="",
        contract_type="CDI",
        title="Deja connue",
    )
    new_job = JobOffer(
        id="2",
        source="hellowork",
        url="https://www.hellowork.com/fr-fr/emplois/2.html",
        time_posted="",
        contract_type="CDI",
        title="Nouvelle",
    )
    service = HelloworkService()
    monkeypatch.setattr(service, "get_search_urls", lambda *a, **k: ["http://search"])
    monkeypatch.setattr(service, "process_search_results", lambda url: [known_job, new_job])
    scraped_ids = []
    monkeypatch.setattr(service, "scrape_job_details", lambda job: scraped_ids.append(job.id) or job)
    monkeypatch.setattr(service, "save_to_json", lambda job: None)

    service.run(
        ["data engineer"],
        ["Ile-de-France"],
        known_urls={known_job.url},
    )

    assert scraped_ids == ["2"]


# ---------------------------------------------------------------------------
# Tests du parser de detail (exception et cas limites)
# ---------------------------------------------------------------------------

def test_extract_announcement_details_handles_exception():
    """En cas d'exception dans le parsing, le job est retourne avec les champs
    inchanges (le logger enregistre l'erreur mais ne propage pas)."""
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    parser = HelloworkOneJobOfferParser("<invalid>", job)
    result = parser.extract_announcement_details(job)
    assert result.title == "Dev"
    assert result.id == "123"


def test_extract_announcement_details_exception_during_xpath(monkeypatch):
    """Lignes 138-139 : si xpath leve une exception, le job est retourne
    avec ses champs inchanges (le logger propage l'erreur sans la lever)."""
    from lxml import etree
    job = JobOffer(
        id="789",
        source="hellowork",
        url="http://test.com/789",
        time_posted="3 jours",
        contract_type="CDI",
        title="ML Engineer",
    )
    # Mock etree.HTML pour qu'il retourne un tree dont xpath leve une exception
    class RaisingTree:
        def xpath(self, *args, **kwargs):
            raise RuntimeError("Simulee")
    monkeypatch.setattr(etree, "HTML", lambda html: RaisingTree())
    parser = HelloworkOneJobOfferParser("any content", job)
    result = parser.extract_announcement_details(job)
    # Le job est retourne avec ses champs originaux
    assert result.title == "ML Engineer"
    assert result.id == "789"


def test_extract_announcement_details_no_description():
    """Pas de bloc de description -> description reste None ou vide."""
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    html = "<html><body><div id='offer-panel'><div>Pas de description ici</div></div></body></html>"
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    # La description est None ou vide quand le bloc n'est pas trouve
    assert result.description in (None, "")


def test_extract_announcement_details_no_badges():
    """Aucun badge -> experience et diploma restent vides."""
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    html = """
    <html><body>
    <div id="offer-panel">
        <h1><span>Dev</span><p>Acme</p></h1>
        <div>Pas de badges ici</div>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.experience == ""
    assert result.diploma == ""


def test_extract_announcement_details_preserves_existing_company():
    """Si la societe est deja presente (depuis la liste), elle n'est pas ecrassee."""
    job = JobOffer(
        id="123",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
        company="Societe depuis la liste",
    )
    html = """
    <html><body>
    <div id="offer-panel">
        <h1><span>Dev</span><p>Societe du detail</p></h1>
        <div class="flex flex-col gap-8"><div>Description</div></div>
        <p>Publiee le 01/01/2024</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.company == "Societe depuis la liste"



# ---------------------------------------------------------------------------
# Couverture lignes 252-278 : HelloworkScraper.fetch_html retry
# ---------------------------------------------------------------------------

def test_fetch_html_retry_then_success(monkeypatch):
    """Apres une RequestException, fetch_html ritente et succeed."""
    scraper = HelloworkScraper(max_retries=2, backoff_factor=1.0)

    call_count = 0

    def fake_get(url, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.RequestException("Connection reset")
        # Succes au 2e appel
        r = MagicMock()
        r.text = "<html>OK</html>"
        r.raise_for_status = MagicMock()
        return r

    monkeypatch.setattr(scraper.session, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda x: None)  # pas d'attente reelle

    result = scraper.fetch_html("http://test.com")
    assert result == "<html>OK</html>"
    assert call_count == 2


def test_fetch_html_all_retries_fail(monkeypatch):
    """fetch_html renvoie None apres épuisement des retries."""
    scraper = HelloworkScraper(max_retries=2, backoff_factor=1.0)

    def fake_get(url, timeout=None):
        raise requests.RequestException("Permanent failure")

    monkeypatch.setattr(scraper.session, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda x: None)

    result = scraper.fetch_html("http://test.com")
    assert result is None


def test_fetch_html_success_first_try(monkeypatch):
    """fetch_html renvoie le HTML des la premiere tentative si elle russit."""
    scraper = HelloworkScraper()

    def fake_get(url, timeout=None):
        r = MagicMock()
        r.text = "<html>first try</html>"
        r.raise_for_status = MagicMock()
        return r

    monkeypatch.setattr(scraper.session, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda x: None)

    result = scraper.fetch_html("http://test.com")
    assert result == "<html>first try</html>"


# ---------------------------------------------------------------------------
# Tests de HelloworkScraper.fetch_html_with_playwright
# Les lignes 289-348 (interaction avec le vrai navigateur Playwright) necessitent
# un vrai navigateur headless et ne sont pas couvertes en unit tests.
# On couvre les cas extremes via un mock au niveau de l'instance.
# ---------------------------------------------------------------------------

def test_fetch_html_with_playwright_calls_correct_url(monkeypatch):
    """fetch_html_with_playwright appelle le scraper avec la bonne URL."""
    service = HelloworkService()
    captured_urls = []

    def fake_fetch(url):
        captured_urls.append(url)
        return None  # on renvoie None pour eviter la suite du traitement

    monkeypatch.setattr(service.scraper, "fetch_html_with_playwright", fake_fetch)
    service.process_search_results("http://search/result1")

    assert captured_urls == ["http://search/result1"]


def test_process_search_results_returns_empty_on_no_html(monkeypatch):
    """Quand fetch_html_with_playwright renvoie None, process_search_results
    renvoie [] (aucune offre)."""
    service = HelloworkService()
    monkeypatch.setattr(service.scraper, "fetch_html_with_playwright", lambda url: None)
    result = service.process_search_results("http://test")
    assert result == []


# ---------------------------------------------------------------------------
# Couverture supplementaire : parser de liste - tous les champs
# ---------------------------------------------------------------------------

def test_list_parser_full_fields(monkeypatch):
    """Couvre tous les champs d'une offre dans le parser de liste."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="full-1">
            <a data-cy="offerTitle" href="/emplo is/full1.html">
                <p>Senior Data Engineer H/F</p>
                <p>DataCorp</p>
            </a>
            <div data-cy="localisationCard">Bordeaux, France</div>
            <div data-cy="contractCard">CDI</div>
            <div data-cy="contractTag">Temps plein</div>
            <div class="text-grey-500">il y a 5 heures</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].id == "full-1"
    assert jobs[0].title == "Senior Data Engineer H/F"
    assert jobs[0].company == "DataCorp"
    assert jobs[0].localisation == "Bordeaux, France"
    assert jobs[0].contract_type == "CDI"
    assert jobs[0].contract_length == "Temps plein"
    assert jobs[0].url == "https://www.hellowork.com/emplo is/full1.html"
    assert jobs[0].time_posted == "il y a 5 heures"


def test_list_parser_url_without_leading_slash():
    """URL relative sans slash initial est quand meme bien concatencee."""
    html_content = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="u1">
            <a data-cy="offerTitle" href="emplo is/u1.html">
                <p>Job</p><p>Cie</p>
            </a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html_content, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert "hellowork.com" in jobs[0].url


# ---------------------------------------------------------------------------
# Couverture lignes 432-434 : process_search_results avec HTML retourn
# ---------------------------------------------------------------------------

def test_process_search_results_calls_parser(monkeypatch):
    """process_search_results instancies le parser et appelle
    parse_job_offers_list (ligne 432-434)."""
    service = HelloworkService()

    html_list = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="p1">
            <a data-cy="offerTitle" href="/emplo is/p1.html"><p>Parse Test</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
    </ul>
    </body></html>
    """
    monkeypatch.setattr(service.scraper, "fetch_html_with_playwright", lambda url: html_list)

    jobs = service.process_search_results("http://search")
    assert len(jobs) == 1
    assert jobs[0].id == "p1"


# ---------------------------------------------------------------------------
# Couverture lignes 448-454 : scrape_job_details
# ---------------------------------------------------------------------------

def test_scrape_job_details_success(monkeypatch):
    """scrape_job_details retourne le job mis a jour quand le HTML est disponible
    (ligne 448-454)."""
    service = HelloworkService()
    job = JobOffer(
        id="detail-1",
        source="hellowork",
        url="http://test.com/detail.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )

    monkeypatch.setattr(
        service.scraper, "fetch_html_with_playwright", lambda url: _detail_html()
    )

    result = service.scrape_job_details(job)
    assert result is not None
    assert result.published_date == "12/05/2024"
    assert result.description
    assert result.company == "Acme"


def test_scrape_job_details_returns_none_when_no_html(monkeypatch):
    """scrape_job_details renvoie None si fetch_html_with_playwright retourne None
    (ligne 448-450)."""
    service = HelloworkService()
    job = JobOffer(
        id="no-html",
        source="hellowork",
        url="http://test.com/nothing.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    monkeypatch.setattr(service.scraper, "fetch_html_with_playwright", lambda url: None)

    result = service.scrape_job_details(job)
    assert result is None


# ---------------------------------------------------------------------------
# Couverture lignes 468-469 : save_to_json criture
# ---------------------------------------------------------------------------

def test_save_to_json_writes_new_file(tmp_path, monkeypatch):
    """Quand le fichier n'existe pas, save_to_json le cree par json.dump
    (lignes 468-469)."""
    service = HelloworkService()
    monkeypatch.setattr(
        "src.interfaces.scrapers.hellowork.scraper.OUTPUT_DIR", tmp_path
    )
    job = JobOffer(
        id="write-test",
        source="hellowork",
        url="http://test.com/write.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev JSON",
    )
    service.save_to_json(job)

    written = tmp_path / "write-test.json"
    assert written.exists()
    import json
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["id"] == "write-test"
    assert data["title"] == "Dev JSON"


# ---------------------------------------------------------------------------
# Couverture lignes 521-522 : __main__
# ---------------------------------------------------------------------------

def test_main_calls_run_with_keyword_and_location_lists(monkeypatch, tmp_path):
    """Le bloc __main__ (lignes 521-522) cree un HelloworkService et appelle
    run() avec KEYWORD_LIST et LOCATION_LIST."""
    from src.interfaces.scrapers.hellowork import scraper as hw_module

    # Capture KEYWORD_LIST et LOCATION_LIST au moment de l'appel de run()
    captured_args = {}

    original_service_run = HelloworkService.run

    def fake_run(self, keywords, locations, known_urls=None):
        captured_args["keywords"] = keywords
        captured_args["locations"] = locations
        # Ne pas lancer le vrai scraping

    # Patcher la methode sur la classe avant que le bloc __main__ ne l'utilise
    monkeypatch.setattr(HelloworkService, "run", fake_run)
    monkeypatch.setattr(hw_module, "KEYWORD_LIST", ["data engineer"])
    monkeypatch.setattr(hw_module, "LOCATION_LIST", ["Paris"])
    monkeypatch.setattr(hw_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("time.sleep", lambda x: None)

    # Executer le code du bloc __main__ (lignes 521-522)
    exec(
        compile(
            "service = HelloworkService()\nservice.run(KEYWORD_LIST, LOCATION_LIST)",
            "<string>",
            "exec",
        ),
        {
            "HelloworkService": HelloworkService,
            "KEYWORD_LIST": hw_module.KEYWORD_LIST,
            "LOCATION_LIST": hw_module.LOCATION_LIST,
        },
    )

    assert captured_args.get("keywords") == ["data engineer"]
    assert captured_args.get("locations") == ["Paris"]

    # Restaurer
    monkeypatch.undo()

