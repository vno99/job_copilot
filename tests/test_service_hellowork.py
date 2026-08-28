from src.core.domain.job_offer import JobOffer
from src.interfaces.scrapers.hellowork.scraper import (
    HelloworkJobOffersListParser,
    HelloworkOneJobOfferParser,
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
