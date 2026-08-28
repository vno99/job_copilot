"""Agent de recherche : ingestion des offres de chaque recherche sauvegardée.

``SearchParametersAgentService.run()`` lit la table ``search_parameters`` et
déclenche, pour chaque ligne **active**, la même ingestion que l'ajout par URL
dans l'UI (``URLJobIngestorService.run(url, max_offers)``) — le matching / CV /
lettre sont immédiatement disponibles via le pipeline existant. Pas de
pagination : une URL = la première page, comme dans l'interface.

``run_parameter_by_id(id)`` exécute une seule recherche, même si elle est
**inactive** : un lancement unitaire (bouton par ligne dans l'UI) est un test
ponctuel qui n'implique aucune activation durable — le statut de la ligne est
inchangé, seuls ``run()`` et le DAG filtrent les inactifs.

Une recherche en échec n'interrompt pas le lot : l'erreur est journalisée et la
suivante est traitée. Le résumé retourné est JSON-sérialisable (poussé en XCom
par la tâche Airflow, lisible dans l'UI).
"""

from typing import Dict, List

from config.logger_config import setup_logging
from src.core.scoring.url_offer_extractor import (
    LLMExtractionError,
    URLScrapingError,
)
from src.infrastructure.db.repositories import search_parameters_repository
from src.infrastructure.db.session import session_scope
from src.services.url_job_ingestor import (
    URLOfferDuplicateError,
    URLIngestResult,
    URLJobIngestorService,
)

logger = setup_logging(__name__)


class SearchParametersAgentService:
    """Orchestre l'ingestion des offres pour les recherches sauvegardées."""

    def __init__(self, ingestor: URLJobIngestorService | None = None):
        self.ingestor = ingestor or URLJobIngestorService()

    def run(self) -> Dict:
        """Traite chaque recherche **active** et retourne un résumé JSON-sérialisable.

        L'échec d'une recherche (URL expirée, LLM indisponible…) est journalisé
        et n'affecte pas les suivantes : le DAG ne retente donc pas tout le lot
        pour une seule recherche en erreur.
        """
        with session_scope() as session:
            all_parameters: List = search_parameters_repository.list_all(session)
        # Seules les recherches actives sont traitées (désactivation dans l'UI).
        parameters = [p for p in all_parameters if p.is_active]
        inactive = len(all_parameters) - len(parameters)
        if inactive:
            logger.info(
                "Agent de recherche : %d recherche(s) inactive(s) ignorée(s)",
                inactive,
            )

        summary = self._new_summary(len(parameters))
        for param in parameters:
            self._process(param, summary)

        logger.info(
            "Agent de recherche : %d/%d recherche(s) traitée(s), %d offre(s) ajoutée(s)",
            summary["succeeded"],
            summary["total"],
            summary["added_offers"],
        )
        return summary

    def run_parameter_by_id(self, param_id: int) -> Dict:
        """Exécute **une** recherche (même pipeline que ``run()``), qu'elle soit
        active ou non — lancement unitaire depuis l'UI. Ne modifie pas
        ``is_active`` : seuls ``run()`` (et le DAG) filtrent les inactifs.

        Raises:
            ValueError: aucune recherche d'id ``param_id`` (→ HTTP 404 côté route).
        """
        with session_scope() as session:
            param = search_parameters_repository.get_by_id(session, param_id)
        if param is None:
            raise ValueError(f"Paramètre de recherche {param_id} introuvable")

        summary = self._new_summary(1)
        self._process(param, summary)
        logger.info(
            "Agent de recherche : recherche %s (%s) — %d/%d, %d offre(s) ajoutée(s)",
            param.id,
            param.title,
            summary["succeeded"],
            summary["total"],
            summary["added_offers"],
        )
        return summary

    @staticmethod
    def _new_summary(total: int) -> Dict:
        """Résumé d'exécution vide (compteurs à zéro), ``total`` recherches."""
        return {
            "total": total,
            "succeeded": 0,
            "duplicates": 0,
            "scraping_failed": 0,
            "llm_failed": 0,
            "other_failed": 0,
            "added_offers": 0,
            "already_present": 0,
            "parameters": [],
        }

    def _process(self, param, summary: Dict) -> Dict:
        """Ingère les offres d'une recherche et cumule son résultat dans
        ``summary`` (compteurs + entrée détaillée). Le titre, la source, l'URL et
        ``max_offers`` sont exposés dans l'entrée pour le front (bannière d'un
        run unitaire). Une erreur est comptée sans interrompre le lot.
        """
        entry: Dict = {
            "id": param.id,
            "title": param.title,
            "source": param.source,
            "url": param.url,
            "max_offers": param.max_offers,
        }
        try:
            result: URLIngestResult = self.ingestor.run(
                param.url, param.max_offers
            )
        except URLOfferDuplicateError as exc:
            summary["duplicates"] += 1
            entry["status"] = "duplicate"
            logger.info(
                "Recherche %s (%s) : offre déjà en base — %s",
                param.id,
                param.url,
                exc,
            )
        except URLScrapingError as exc:
            summary["scraping_failed"] += 1
            entry["status"] = "scraping_failed"
            logger.warning(
                "Recherche %s (%s) : récupération impossible — %s",
                param.id,
                param.url,
                exc,
            )
        except LLMExtractionError as exc:
            summary["llm_failed"] += 1
            entry["status"] = "llm_failed"
            logger.warning(
                "Recherche %s (%s) : LLM indisponible — %s",
                param.id,
                param.url,
                exc,
            )
        except Exception as exc:  # noqa: BLE001 — une recherche ne doit pas tuer le lot
            summary["other_failed"] += 1
            entry["status"] = "error"
            logger.exception(
                "Recherche %s (%s) : erreur inattendue — %s",
                param.id,
                param.url,
                exc,
            )
        else:
            summary["succeeded"] += 1
            summary["added_offers"] += result.added
            summary["already_present"] += result.already_present
            entry["status"] = "ok"
            entry["added"] = result.added
            entry["already_present"] = result.already_present
            logger.info(
                "Recherche %s (%s) : %d offre(s) ajoutée(s), %d déjà présente(s)",
                param.id,
                param.url,
                result.added,
                result.already_present,
            )
        summary["parameters"].append(entry)
        return entry
