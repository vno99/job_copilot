from datetime import datetime, timedelta

from airflow.sdk import dag, task
from dateutil import tz

from src.config.settings import KEYWORD_LIST, LOCATION_LIST
from src.infrastructure.db.repositories import job_offer_repository
from src.infrastructure.db.session import session_scope
from src.interfaces.scrapers.hellowork.scraper import HelloworkService
from src.services.job_parser import JobParserService

local_tz = tz.gettz("Europe/Paris")

default_args = {
    "owner": "airflow",
    "start_date": datetime(2026, 5, 1, tzinfo=local_tz),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="job_copilot",
    description=(
        "Pipeline d'emploi : scrap des offres et ingestion en base. "
        "Le matching offre/profil et la génération de CV recomposé sont "
        "déclenchés à la demande (interface de validation)."
    ),
    default_args=default_args,
    schedule="*/20 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["job"],
)
def job_copilot():

    @task(task_id="scrape_hellowork")
    def scrape_hellowork():
        # On ne re-scrape pas les offres déjà connues en base : le scraper
        # reçoit les URLs des plus récentes et les ignore.
        with session_scope() as session:
            known_urls = set(job_offer_repository.recent_urls(session, limit=50))
        service = HelloworkService()
        service.run(KEYWORD_LIST, LOCATION_LIST, known_urls=known_urls)
        return True

    @task(task_id="ingest_job_offers")
    def ingest_job_offers():
        return JobParserService().run()

    # NB : le pipeline automatique s'arrête après l'ingestion. Le matching
    # offre/profil et la génération de CV recomposé sont volontairement absents du
    # DAG : ils sont déclenchés à la demande via l'API (interface de validation) :
    #   1. POST /profiles                 -> upload CV (profil candidat)
    #   2. POST /matching/run             -> matching de l'offre
    #   3. POST /cvs/generate             -> CV recomposé (Markdown)

    s = scrape_hellowork()
    i = ingest_job_offers()

    s >> i


job_copilot()
