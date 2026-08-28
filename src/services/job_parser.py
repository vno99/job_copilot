"""Agent ``job_parser`` : ingestion et normalisation des offres d'emploi.

Lit les offres scrappées (JSON dans ``data/hellowork/``), les normalise
(1:1 sur la table ``job_offer``) puis les upsert en base avec dédoublonnage
sur ``content_hash``.
"""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

from config.logger_config import setup_logging
from src.config.settings import HELLOWORK_OUTPUT_DIR
from src.core.domain.job_offer import JobOffer
from src.core.scoring.score_engine import extract_skills
from src.infrastructure.db.repositories.job_offer_repository import upsert_many
from src.infrastructure.db.session import session_scope

logger = setup_logging(__name__)


def _parse_published_date(value: Any) -> date | None:
    """Convertit une date publiée (``DD/MM/YYYY`` ou ISO) en ``date``."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value, fmt).date()
        except ValueError:
            continue
    logger.warning("Format de date non reconnu: %r", value)
    return None


def _diploma_to_text(value: Any) -> str | None:
    """Normalise le champ diplôme : liste -> texte, texte tel quel."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x) or None
    return str(value).strip() or None


def _compute_content_hash(raw: Dict[str, Any]) -> str:
    """Empreinte stable du payload brut (clés triées)."""
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_job_offer(job_offer: JobOffer) -> Dict[str, Any]:
    """Convertit une ``JobOffer`` en dictionnaire mappé sur la table ``job_offer``."""
    raw = job_offer.to_dict()

    return {
        "source": (raw.get("source") or "").strip().lower(),
        "source_job_id": str(raw.get("id")),
        "url": (raw.get("url") or "").strip(),
        "title": (raw.get("title") or "").strip() or None,
        "company": (raw.get("company") or "").strip() or None,
        "location": (raw.get("localisation") or "").strip() or None,
        "contract_type": (raw.get("contract_type") or "").strip() or None,
        "published_date": _parse_published_date(raw.get("published_date")),
        "experience": (raw.get("experience") or "") or None,
        "diploma": _diploma_to_text(raw.get("diploma")),
        "description": (raw.get("description") or "").strip() or None,
        "skills_extracted": extract_skills(raw.get("description") or ""),
        "raw_payload": raw,
        "content_hash": _compute_content_hash(raw),
    }


def load_job_offer(json_path: Path) -> JobOffer:
    """Charge un JSON d'offre scrapée en objet ``JobOffer``."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return JobOffer(
        id=data.get("id"),
        source=data.get("source"),
        url=data.get("url"),
        time_posted=data.get("time_posted"),
        contract_type=data.get("contract_type"),
        title=data.get("title", ""),
        company=data.get("company", ""),
        localisation=data.get("localisation", ""),
        contract_length=data.get("contract_length", ""),
        description=data.get("description"),
        published_date=data.get("published_date"),
        experience=data.get("experience"),
        diploma=data.get("diploma"),
    )


class JobParserService:
    """Orchestre la lecture des offres et leur upsert en base."""

    def run(self, output_dir: Path | None = None) -> Dict[str, int]:
        """Ingère toutes les offres d'un dossier de JSON scrappés.

        Returns:
            Dict avec les compteurs ``ingested``, ``updated``, ``unchanged``.
        """
        output_dir = output_dir or HELLOWORK_OUTPUT_DIR

        if not output_dir.exists():
            logger.warning("Dossier d'offres introuvable: %s", output_dir)
            return {"ingested": 0, "updated": 0, "unchanged": 0}

        rows: List[Dict[str, Any]] = []
        for json_path in sorted(output_dir.glob("*.json")):
            try:
                job_offer = load_job_offer(json_path)
                rows.append(normalize_job_offer(job_offer))
                logger.info("Offre normalisée: %s", json_path.name)
            except Exception as e:
                logger.exception("Erreur de parsing de %s: %s", json_path, e)

        if not rows:
            return {"ingested": 0, "updated": 0, "unchanged": 0}

        with session_scope() as session:
            ingested, updated, unchanged = upsert_many(session, rows)

        logger.info(
            "Ingestion terminée: ingested=%d updated=%d unchanged=%d",
            ingested,
            updated,
            unchanged,
        )
        return {"ingested": ingested, "updated": updated, "unchanged": unchanged}
