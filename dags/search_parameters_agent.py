from datetime import datetime, timedelta

from airflow.sdk import dag, task
from dateutil import tz

from src.services.search_parameters_agent import SearchParametersAgentService

local_tz = tz.gettz("Europe/Paris")

default_args = {
    "owner": "airflow",
    "start_date": datetime(2026, 5, 1, tzinfo=local_tz),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="search_parameters_agent",
    description=(
        "Agent de recherche : pour chaque paramètre de recherche, ingère les "
        "offres de l'URL (même pipeline que l'ajout par URL dans l'UI). "
        "Matching/CV/lettre restent à la demande."
    ),
    default_args=default_args,
    schedule="0 * * * *",  # toutes les heures, sans pagination
    catchup=False,
    max_active_runs=1,
    # Le défaut global est « DAG créé pausé » (dags_are_paused_at_creation) :
    # on lève explicitement pour que l'agent soit actif dès sa création.
    is_paused_upon_creation=False,
    tags=["search", "job"],
)
def search_parameters_agent():

    @task(task_id="ingest_search_parameters")
    def ingest_search_parameters():
        # Le service n'est instancié qu'à l'exécution de la tâche (pas au parse
        # du DAG) : Playwright et le LLM ne sont chargés qu'au moment du run.
        return SearchParametersAgentService().run()

    ingest_search_parameters()


search_parameters_agent()
