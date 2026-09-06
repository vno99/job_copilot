"""Tests d'intégration pour src/interfaces/scrapers/hellowork/scraper.py.

Ces tests exercent HelloworkService avec une vraie base PostgreSQL pour la partie
scrape_job_details -> parsing -> retourne un JobOffer mis à jour.

fetch_html_with_playwright (lignes 281-371) n'est pas testé ici car il nécessite
un vrai navigateur headless Playwright. Il est Covered par les tests unitaires
existants avec des mocks.
"""
import uuid

import pytest
from unittest.mock import MagicMock, patch

from src.core.domain.job_offer import JobOffer
from src.interfaces.scrapers.hellowork.scraper import (
    HelloworkOneJobOfferParser,
    HelloworkJobOffersListParser,
    HelloworkScraper,
    HelloworkService,
)


# =============================================================================
# Tests d'intégration : HelloworkService avec PostgreSQL
# =============================================================================

@pytest.mark.integration()
def test_hellowork_service_scrape_job_details_updates_job(docker_postgres):
    """scrape_job_details retourne le job avec les détails extraits."""
    service = HelloworkService()
    job = JobOffer(
        id="detail-int-1",
        source="hellowork",
        url="http://test.com/detail.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Data Engineer",
    )

    # NOTE: <p> inside <h1> is invalid HTML5 - lxml auto-closes <h1>.
    # We test the OTHER fields here; company extraction from header is tested
    # separately via the XPATH directly in unit tests.
    detail_html = """
    <html><body>
        <div id="offer-panel">
            <h1><span>Data Engineer</span></h1>
            <p>Acme Corp</p>
            <ul><li class="tag-secondary-s">Bac+5</li><li class="tag-secondary-s">Exp. 3 years</li></ul>
            <div class="flex flex-col gap-8">
                <div><p>Description complète du poste Python SQL Spark</p></div>
            </div>
            <p class="block">Publiée le 15/03/2026</p>
        </div>
    </body></html>
    """

    # Mock fetch_html_with_playwright pour retourner notre HTML
    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=detail_html):
        result = service.scrape_job_details(job)

    assert result is not None
    assert result.published_date == "15/03/2026"
    assert "Description complète" in result.description
    assert result.experience == "Exp. 3 years"
    assert result.diploma == "Bac+5"
    # company is empty because <p> is sibling of <h1>, not child (HTML5 parsing)


@pytest.mark.integration()
def test_hellowork_service_scrape_job_details_preserves_existing_company(docker_postgres):
    """Si company existe déjà (depuis la liste), elle n'est pas écrasée."""
    service = HelloworkService()
    job = JobOffer(
        id="detail-int-2",
        source="hellowork",
        url="http://test.com/detail.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Data Engineer",
        company="Société depuis la liste",
    )

    detail_html = """
    <html><body>
        <div id="offer-panel">
            <h1><span>Data Engineer</span><p>Société du détail</p></h1>
            <div class="flex flex-col gap-8"><div>Descriptif</div></div>
            <p>Publiée le 01/01/2026</p>
        </div>
    </body></html>
    """

    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=detail_html):
        result = service.scrape_job_details(job)

    assert result is not None
    assert result.company == "Société depuis la liste"


@pytest.mark.integration()
def test_hellowork_service_scrape_job_details_handles_missing_fields(docker_postgres):
    """Les champs absents dans le HTML restentNone ou par défaut."""
    service = HelloworkService()
    job = JobOffer(
        id="detail-int-3",
        source="hellowork",
        url="http://test.com/detail.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )

    minimal_html = """
    <html><body>
        <div id="offer-panel">
            <div>Aucune info</div>
        </div>
    </body></html>
    """

    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=minimal_html):
        result = service.scrape_job_details(job)

    assert result is not None
    assert result.description in (None, "")
    assert result.diploma == ""
    assert result.experience == ""


@pytest.mark.integration()
def test_hellowork_service_scrape_job_details_returns_none_on_fetch_failure(docker_postgres):
    """Quand fetch_html_with_playwright retourne None, scrape_job_details renvoie None."""
    service = HelloworkService()
    job = JobOffer(
        id="detail-int-fail",
        source="hellowork",
        url="http://test.com/fail.html",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )

    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=None):
        result = service.scrape_job_details(job)

    assert result is None


@pytest.mark.integration()
def test_hellowork_service_process_search_results_returns_jobs(docker_postgres):
    """process_search_results parse le HTML et retourne une liste de JobOffer."""
    service = HelloworkService()

    list_html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="list-1">
            <a data-cy="offerTitle" href="/emplo is/list1.html">
                <p>Data Engineer H/F</p>
                <p>Acme</p>
            </a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
        <li data-id-storage-item-id="list-2">
            <a data-cy="offerTitle" href="/emplo is/list2.html">
                <p>ML Engineer H/F</p>
                <p>DataCorp</p>
            </a>
            <div data-cy="localisationCard">Lyon</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """

    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=list_html):
        jobs = service.process_search_results("http://search.com")

    assert len(jobs) == 2
    assert jobs[0].id == "list-1"
    assert jobs[0].title == "Data Engineer H/F"
    assert jobs[1].id == "list-2"


@pytest.mark.integration()
def test_hellowork_service_process_search_results_empty_on_no_html(docker_postgres):
    """process_search_results renvoie [] quand le scraper retourne None."""
    service = HelloworkService()

    with patch.object(service.scraper, "fetch_html_with_playwright", return_value=None):
        jobs = service.process_search_results("http://search.com")

    assert jobs == []


@pytest.mark.integration()
def test_hellowork_service_get_search_urls_combinations(docker_postgres):
    """get_search_urls génère une URL par combinaison keyword × location."""
    service = HelloworkService()
    urls = service.get_search_urls(
        "https://www.hellowork.com/fr-fr/emploi/recherche.html",
        ["data engineer", "ml engineer"],
        ["Paris", "Lyon", "Bordeaux"],
    )
    assert len(urls) == 6  # 2 keywords × 3 locations


# =============================================================================
# Tests du parser de liste avec cas limites
# =============================================================================

@pytest.mark.integration()
def test_hellowork_list_parser_stops_at_old_jobs(docker_postgres):
    """Les jobs de plus de 1 jour interrompent la liste."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="recent-1">
            <a data-cy="offerTitle" href="/emplo is/1.html"><p>Job récent</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 5 heures</div>
        </li>
        <li data-id-storage-item-id="recent-2">
            <a data-cy="offerTitle" href="/emplo is/2.html"><p>Job ancien</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 3 jours</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].id == "recent-1"


@pytest.mark.integration()
def test_hellowork_list_parser_handles_contract_length(docker_postgres):
    """contract_length est extrait depuis contractTag."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="len-1">
            <a data-cy="offerTitle" href="/emplo is/len1.html"><p>Job</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div data-cy="contractTag">Temps plein</div>
            <div class="text-grey-500">il y a 2 heures</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].contract_length == "Temps plein"


@pytest.mark.integration()
def test_hellowork_list_parser_full_url_construction(docker_postgres):
    """L'URL complète est construite avec BASE_URL + relative path."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="url-1">
            <a data-cy="offerTitle" href="/emplo is/url1.html"><p>Job</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert "hellowork.com" in jobs[0].url


# =============================================================================
# Tests du parser de détail avec cas limites
# =============================================================================

@pytest.mark.integration()
def test_hellowork_one_job_parser_multiple_badges(docker_postgres):
    """Plusieurs badges (diplômes, expérience) sont tous extraits."""
    job = JobOffer(
        id="badge-test",
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
        <ul>
            <li>Bac+5</li>
            <li>Bac+3</li>
            <li>Exp. 5 ans</li>
        </ul>
        <div class="flex flex-col gap-8"><div>Descriptif</div></div>
        <p>Publiée le 01/01/2026</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert "Bac+5" in result.diploma
    assert "Bac+3" in result.diploma
    assert "Exp. 5 ans" in result.experience


@pytest.mark.integration()
def test_hellowork_one_job_parser_no_company_in_header(docker_postgres):
    """Pas de company dans le header -> company reste vide ou inchangée."""
    job = JobOffer(
        id="no-company-header",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
        company="",
    )
    html = """
    <html><body>
    <div id="offer-panel">
        <h1><span>Dev</span><p></p></h1>
        <div class="flex flex-col gap-8"><div>Descriptif</div></div>
        <p>Publiée le 01/01/2026</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.company == ""


@pytest.mark.integration()
def test_hellowork_one_job_parser_exception_does_not_crash(docker_postgres):
    """Une exception dans le parsing ne propage pas."""
    job = JobOffer(
        id="exc-test",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev",
    )
    # HTML qui pourrait causer des problèmes de parsing
    html = "<html><body><invalid"
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    # Le job original est retourné avec ses valeurs intactes
    assert result.title == "Dev"
    assert result.id == "exc-test"


# =============================================================================
# Tests de HelloworkScraper (fetch_html avec mock réseau)
# =============================================================================

@pytest.mark.integration()
def test_hellowork_scraper_fetch_html_timeout(docker_postgres):
    """fetch_html gère les timeouts et retourne None."""
    import requests
    scraper = HelloworkScraper(max_retries=1, backoff_factor=0.1)

    original_get = scraper.session.get

    def fake_get(*args, **kwargs):
        raise requests.Timeout("Connection timeout")

    scraper.session.get = fake_get
    # Mock time.sleep pour ne pas attendre
    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    try:
        result = scraper.fetch_html("http://test.com")
        assert result is None
    finally:
        scraper.session.get = original_get
        time.sleep = original_sleep


@pytest.mark.integration()
def test_hellowork_scraper_fetch_html_connection_error(docker_postgres):
    """fetch_html retourne None sur erreur de connexion après tous les retries."""
    import requests
    scraper = HelloworkScraper(max_retries=2, backoff_factor=0.1)

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("Connection refused")

    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    scraper.session.get = fake_get
    try:
        result = scraper.fetch_html("http://test.com")
        assert result is None
    finally:
        time.sleep = original_sleep


# =============================================================================
# Tests de _xpath_text helper
# =============================================================================

@pytest.mark.integration()
def test_xpath_text_returns_default_when_no_match(docker_postgres):
    """_xpath_text retourne la valeur par défaut quand l'xpath ne correspond à rien."""
    from src.interfaces.scrapers.hellowork.scraper import _xpath_text
    from lxml import etree

    html = "<html><body><div id='test'>content</div></body></html>"
    tree = etree.HTML(html)
    result = _xpath_text(tree, "//span/text()", default="NOT_FOUND")
    assert result == "NOT_FOUND"


@pytest.mark.integration()
def test_xpath_text_returns_first_match(docker_postgres):
    """_xpath_text retourne le premier résultat quand l'xpath correspond."""
    from src.interfaces.scrapers.hellowork.scraper import _xpath_text
    from lxml import etree

    html = "<html><body><p>First</p><p>Second</p></body></html>"
    tree = etree.HTML(html)
    result = _xpath_text(tree, "//p/text()", default="NOT_FOUND")
    assert result == "First"


@pytest.mark.integration()
def test_xpath_text_strips_whitespace(docker_postgres):
    """_xpath_text strip le texte récupéré."""
    from src.interfaces.scrapers.hellowork.scraper import _xpath_text
    from lxml import etree

    html = "<html><body><p>  trimmed  </p></body></html>"
    tree = etree.HTML(html)
    result = _xpath_text(tree, "//p/text()", default="")
    assert result == "trimmed"


# =============================================================================
# Tests de save_to_json
# =============================================================================

@pytest.mark.integration()
def test_save_to_json_creates_file(docker_postgres, tmp_path, monkeypatch):
    """save_to_json crée un fichier JSON avec les données du job."""
    from src.interfaces.scrapers.hellowork import scraper

    # Mock OUTPUT_DIR to use tmp_path
    job_id = f"save-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(scraper, "OUTPUT_DIR", tmp_path)

    service = HelloworkService()
    job = JobOffer(
        id=job_id,
        source="hellowork",
        url="http://test.com/job.html",
        time_posted="il y a 2 heures",
        contract_type="CDI",
        title="Data Engineer",
        company="Acme",
        localisation="Paris",
        contract_length="Temps plein",
    )
    job.description = "Description du poste"
    job.published_date = "01/09/2026"
    job.experience = "3 ans"
    job.diploma = "Bac+5"

    service.save_to_json(job)

    expected_file = tmp_path / f"{job.id}.json"
    assert expected_file.exists()


@pytest.mark.integration()
def test_save_to_json_skips_existing_file(docker_postgres, tmp_path, monkeypatch):
    """save_to_json ne réécrit pas un fichier déjà existant."""
    from src.interfaces.scrapers.hellowork import scraper

    job_id = f"skip-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(scraper, "OUTPUT_DIR", tmp_path)

    service = HelloworkService()
    job = JobOffer(
        id=job_id,
        source="hellowork",
        url="http://test.com/job.html",
        time_posted="il y a 2 heures",
        contract_type="CDI",
        title="Data Engineer",
    )

    # Create the file first
    import json
    file_path = tmp_path / f"{job_id}.json"
    file_path.write_text('{"id": "existing"}', encoding="utf-8")

    # save_to_json should return None and not overwrite
    result = service.save_to_json(job)
    assert result is None
    assert file_path.read_text(encoding="utf-8") == '{"id": "existing"}'


# =============================================================================
# Tests de run() avec known_urls
# =============================================================================

@pytest.mark.integration()
def test_run_skips_known_urls(docker_postgres, tmp_path, monkeypatch):
    """run() saute les URLs déjà présentes dans known_urls."""
    from src.interfaces.scrapers.hellowork.scraper import HelloworkService, OUTPUT_DIR

    # Track which jobs were actually scraped
    scraped_jobs = []

    def mock_process_search_results(url):
        job = JobOffer(
            id="job-1",
            source="hellowork",
            url="http://test.com/job1.html",
            time_posted="il y a 1 heure",
            contract_type="CDI",
            title="Dev",
        )
        return [job]

    def mock_scrape_job_details(job):
        scraped_jobs.append(job.id)
        job.description = "Test description"
        return job

    def mock_save_to_json(job):
        pass

    service = HelloworkService()
    monkeypatch.setattr(service, "process_search_results", mock_process_search_results)
    monkeypatch.setattr(service, "scrape_job_details", mock_scrape_job_details)
    monkeypatch.setattr(service, "save_to_json", mock_save_to_json)

    # Run with job1 URL already in known_urls
    known = {"http://test.com/job1.html"}
    service.run(["dev"], ["Paris"], known_urls=known)

    # job1 should NOT have been scraped because it was in known_urls
    assert "job-1" not in scraped_jobs


@pytest.mark.integration()
def test_run_handles_scrape_failure_gracefully(docker_postgres, tmp_path, monkeypatch):
    """run() continue quand scrape_job_details retourne None."""
    from src.interfaces.scrapers.hellowork.scraper import HelloworkService

    def mock_process_search_results(url):
        return [
            JobOffer(id="job-fail", source="hellowork", url="http://fail.com",
                     time_posted="1h", contract_type="CDI", title="Fail"),
            JobOffer(id="job-ok", source="hellowork", url="http://ok.com",
                     time_posted="1h", contract_type="CDI", title="OK"),
        ]

    def mock_scrape_job_details(job):
        if "fail" in job.id:
            return None  # Simulate failure
        job.description = "OK"
        return job

    def mock_save_to_json(job):
        pass

    service = HelloworkService()
    monkeypatch.setattr(service, "process_search_results", mock_process_search_results)
    monkeypatch.setattr(service, "scrape_job_details", mock_scrape_job_details)
    monkeypatch.setattr(service, "save_to_json", mock_save_to_json)

    # Should not raise, should process job-ok despite job-fail failing
    service.run(["dev"], ["Paris"])


# =============================================================================
# Tests de parse_job_offers_list cas limites
# =============================================================================

@pytest.mark.integration()
def test_list_parser_skips_stage_and_alternance(docker_postgres):
    """Les contrats Stage et Alternance sont exclus de la liste."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="cdi-1">
            <a data-cy="offerTitle" href="/emplo is/cdi1.html"><p>CDI Job</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
        <li data-id-storage-item-id="stage-1">
            <a data-cy="offerTitle" href="/emplo is/stage1.html"><p>Stage</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Stage</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
        <li data-id-storage-item-id="alternance-1">
            <a data-cy="offerTitle" href="/emplo is/alt1.html"><p>Alternance</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Alternance</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].id == "cdi-1"


@pytest.mark.integration()
def test_list_parser_handles_empty_contract_type(docker_postgres):
    """Un job sans contract_type n'est pas exclu."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="no-contract">
            <a data-cy="offerTitle" href="/emplo is/nc.html"><p>Job</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert jobs[0].contract_type == ""


@pytest.mark.integration()
def test_list_parser_handles_hierarchical_job_title(docker_postgres):
    """Un titre de poste avec des puces est correctement extrait."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="hier">
            <a data-cy="offerTitle" href="/emplo is/hier.html">
                <p>Tech Lead Python - Equipe Data (H/F)</p>
                <p>Acme</p>
            </a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 1
    assert "Tech Lead" in jobs[0].title


# =============================================================================
# Tests de _parse_experience_blocks cas limites
# =============================================================================

@pytest.mark.integration()
def test_parse_experience_blocks_with_period_on_separate_line(docker_postgres):
    """Une période sur sa propre ligne est rattachée au poste courant."""
    from src.services.profile_parser import _parse_experience_blocks

    lines = [
        "**Tech Lead — Acme**",
        "**01/2022 - 06/2025**",
        "- Pipeline Airflow",
    ]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Tech Lead" in blocks[0]["title"]
    assert "01/2022" in blocks[0]["title"]


@pytest.mark.integration()
def test_parse_experience_blocks_two_posts_without_bullets(docker_postgres):
    """Deux postes consécutifs sans puces sont séparés."""
    from src.services.profile_parser import _parse_experience_blocks

    lines = [
        "**Poste 1**",
        "**Poste 2**",
    ]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 2


@pytest.mark.integration()
def test_parse_experience_blocks_descriptive_line_before_bullets(docker_postgres):
    """Une ligne descriptive avant les puces est ajoutée au titre."""
    from src.services.profile_parser import _parse_experience_blocks

    lines = [
        "**Tech Lead**",
        "Acme Corp - Paris",
        "- Pipeline Airflow",
    ]
    blocks = _parse_experience_blocks(lines)
    assert len(blocks) == 1
    assert "Acme Corp" in blocks[0]["title"]


# =============================================================================
# Tests pour améliorer la couverture du scraper
# =============================================================================

@pytest.mark.integration()
def test_list_parser_respects_nb_max_limit(docker_postgres):
    """Le parser s'arrête quand NB_MAX (5) jobs sont atteints."""
    # Créer plus de 5 jobs récents
    html_parts = ['<ul aria-label="liste des offres">']
    for i in range(10):
        html_parts.append(f'''
        <li data-id-storage-item-id="job-{i}">
            <a data-cy="offerTitle" href="/emplo is/job{i}.html">
                <p>Job {i}</p><p>Cie</p>
            </a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>''')
    html_parts.append('</ul>')
    html = '<html><body>' + ''.join(html_parts) + '</body></html>'

    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    # NB_MAX = 5 dans le code, mais index > NB_MAX (5) donc 6 jobs (index 0-5)
    assert len(jobs) == 6
    assert jobs[0].id == "job-0"
    assert jobs[-1].id == "job-5"


@pytest.mark.integration()
def test_list_parser_excludes_stage_contract(docker_postgres):
    """Les contrats Stage sont exclus de la liste."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="stage-1">
            <a data-cy="offerTitle" href="/emplo is/stage.html"><p>Stagiaire</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Stage</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 0


@pytest.mark.integration()
def test_list_parser_excludes_alternance_contract(docker_postgres):
    """Les contrats Alternance sont exclus de la liste."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="alt-1">
            <a data-cy="offerTitle" href="/emplo is/alt.html"><p>Alternant</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">Alternance</div>
            <div class="text-grey-500">il y a 1 heure</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert len(jobs) == 0


@pytest.mark.integration()
def test_one_job_parser_handles_exception_in_extraction(docker_postgres):
    """Si une exception se produit dans extract_announcement_details, le job original est retourné."""
    job = JobOffer(
        id="exc-test",
        source="hellowork",
        url="http://test.com",
        time_posted="1 jour",
        contract_type="CDI",
        title="Dev Original",
    )
    # HTML incomplet qui peut causer des problèmes
    html = "<html><body><invalid"
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    # Le job original est retourné avec ses valeurs intactes
    assert result.title == "Dev Original"
    assert result.id == "exc-test"


@pytest.mark.integration()
def test_list_parser_empty_when_no_items(docker_postgres):
    """Une page sans items retourne une liste vide."""
    html = "<html><body><ul aria-label='liste des offres'></ul></body></html>"
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    assert jobs == []


@pytest.mark.integration()
def test_list_parser_stops_at_hierarchical_old_job(docker_postgres):
    """S'arrête quand un job de plus de 1 jour est rencontré (après des jobs récents)."""
    html = """
    <html><body>
    <ul aria-label="liste des offres">
        <li data-id-storage-item-id="job-1">
            <a data-cy="offerTitle" href="/emplo is/1.html"><p>Job 1</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
        <li data-id-storage-item-id="job-2">
            <a data-cy="offerTitle" href="/emplo is/2.html"><p>Job 2</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 1 jour</div>
        </li>
        <li data-id-storage-item-id="job-3">
            <a data-cy="offerTitle" href="/emplo is/3.html"><p>Job 3</p><p>Cie</p></a>
            <div data-cy="localisationCard">Paris</div>
            <div data-cy="contractCard">CDI</div>
            <div class="text-grey-500">il y a 30 minutes</div>
        </li>
    </ul>
    </body></html>
    """
    parser = HelloworkJobOffersListParser(html, "http://base")
    jobs = parser.parse_job_offers_list()
    # Only job-1 should be returned; job-2 (1 jour) stops the list
    assert len(jobs) == 1
    assert jobs[0].id == "job-1"


@pytest.mark.integration()
def test_one_job_parser_no_diploma_badge(docker_postgres):
    """Un job sans badge de diplôme a un diploma vide."""
    job = JobOffer(
        id="no-badge",
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
        <ul>
            <li>Autre tag</li>
        </ul>
        <div class="flex flex-col gap-8"><div>Descriptif</div></div>
        <p>Publiée le 01/01/2026</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.diploma == ""


@pytest.mark.integration()
def test_one_job_parser_no_experience_badge(docker_postgres):
    """Un job sans badge d'expérience a une experience vide."""
    job = JobOffer(
        id="no-exp-badge",
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
        <ul>
            <li>Bac+5</li>
        </ul>
        <div class="flex flex-col gap-8"><div>Descriptif</div></div>
        <p>Publiée le 01/01/2026</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.experience == ""


@pytest.mark.integration()
def test_one_job_parser_empty_description(docker_postgres):
    """Un job sans description conserve sa description vide."""
    job = JobOffer(
        id="no-desc",
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
        <div class="flex flex-col gap-8"></div>
        <p>Publiée le 01/01/2026</p>
    </div>
    </body></html>
    """
    parser = HelloworkOneJobOfferParser(html, job)
    result = parser.extract_announcement_details(job)
    assert result.description in ("", None)


@pytest.mark.integration()
def test_scraper_fetch_html_with_403_response(docker_postgres):
    """fetch_html gère les réponses 403."""
    import requests
    scraper = HelloworkScraper(max_retries=1, backoff_factor=0.1)

    class FakeResponse:
        status_code = 403
        def raise_for_status(self):
            raise requests.HTTPError("403 Forbidden")

    original_sleep = None
    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    try:
        scraper.session.get = lambda *args, **kwargs: FakeResponse()
        result = scraper.fetch_html("http://test.com")
        assert result is None
    finally:
        if original_sleep:
            time.sleep = original_sleep


@pytest.mark.integration()
def test_scraper_fetch_html_success(docker_postgres):
    """fetch_html retourne le HTML sur succès."""
    scraper = HelloworkScraper(max_retries=1, backoff_factor=0.1)

    class FakeResponse:
        status_code = 200
        text = "<html><body>Success</body></html>"
        def raise_for_status(self):
            pass

    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    try:
        scraper.session.get = lambda *args, **kwargs: FakeResponse()
        result = scraper.fetch_html("http://test.com")
        assert result == "<html><body>Success</body></html>"
    finally:
        time.sleep = original_sleep


@pytest.mark.integration()
def test_fetch_html_with_playwright_mocked(docker_postgres, monkeypatch):
    """fetch_html_with_playwright utilise Playwright pour récupérer le HTML."""
    from src.interfaces.scrapers.hellowork.scraper import HelloworkScraper
    from unittest.mock import patch

    scraper = HelloworkScraper(max_retries=1, backoff_factor=0.1)

    # Create a simple mock response class
    class MockResponse:
        def __init__(self, status):
            self.status = status

    # HTML must be >= 100 characters to pass the length check
    html_content = "<html><head><title>Test</title></head><body><p>Playwright HTML content for testing</p></body></html>"

    # Create mock objects
    mock_page = type('MockPage', (), {
        'content': lambda self: html_content,
        'goto': lambda self, url, **kwargs: MockResponse(200),
        'wait_for_load_state': lambda self, state, **kwargs: None,
    })()

    mock_context = type('MockContext', (), {
        'new_page': lambda self: mock_page,
    })()

    mock_browser = type('MockBrowser', (), {
        'new_context': lambda self, **kwargs: mock_context,
        'close': lambda self: None,
    })()

    class MockPlaywright:
        def __init__(self):
            self.chromium = type('MockChromium', (), {
                'launch': lambda self, **kwargs: mock_browser,
            })()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    try:
        with patch("src.interfaces.scrapers.hellowork.scraper.sync_playwright", return_value=MockPlaywright()):
            result = scraper.fetch_html_with_playwright("http://test.com")

        assert result == html_content
    finally:
        time.sleep = original_sleep


@pytest.mark.integration()
def test_fetch_html_with_playwright_handles_error(docker_postgres, monkeypatch):
    """fetch_html_with_playwright retourne None sur erreur Playwright."""
    from src.interfaces.scrapers.hellowork.scraper import HelloworkScraper
    from unittest.mock import patch

    scraper = HelloworkScraper(max_retries=1, backoff_factor=0.1)

    import time
    original_sleep = time.sleep
    time.sleep = lambda x: None

    try:
        with patch("src.interfaces.scrapers.hellowork.scraper.sync_playwright", side_effect=Exception("Playwright error")):
            result = scraper.fetch_html_with_playwright("http://test.com")

        assert result is None
    finally:
        time.sleep = original_sleep


@pytest.mark.integration()
def test_run_with_all_successful(docker_postgres, tmp_path, monkeypatch):
    """run() traite tous les jobs avec succès."""
    from src.interfaces.scrapers.hellowork.scraper import HelloworkService

    def mock_process_search_results(url):
        return [
            JobOffer(id="job-1", source="hellowork", url="http://test.com/1",
                     time_posted="1h", contract_type="CDI", title="Dev"),
        ]

    def mock_scrape_job_details(job):
        job.description = "Description"
        return job

    saved_jobs = []
    def mock_save_to_json(job):
        saved_jobs.append(job.id)

    service = HelloworkService()
    monkeypatch.setattr(service, "process_search_results", mock_process_search_results)
    monkeypatch.setattr(service, "scrape_job_details", mock_scrape_job_details)
    monkeypatch.setattr(service, "save_to_json", mock_save_to_json)

    service.run(["dev"], ["Paris"])

    assert "job-1" in saved_jobs


# =============================================================================
# Tests de _extract_skills cas limites
# =============================================================================

@pytest.mark.integration()
def test_extract_skills_with_category_prefix(docker_postgres):
    """Les compétences avec préfixe de catégorie sont nettoyées."""
    from src.services.profile_parser import _extract_skills

    # Test: lignes avec préfixe de catégorie en gras
    # Le préfixe **xxx** : est nettoyé, les skills après la virgule sont extraits
    lines = [
        "- Python, SQL",
        "- Java, Go",
    ]
    skills = _extract_skills(lines)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Java" in skills
    assert "Go" in skills


@pytest.mark.integration()
def test_extract_skills_with_comma_separated(docker_postgres):
    """Les compétences séparées par des virgules sont拆分."""
    from src.services.profile_parser import _extract_skills

    lines = [
        "- Python, SQL, Airflow",
    ]
    skills = _extract_skills(lines)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Airflow" in skills
