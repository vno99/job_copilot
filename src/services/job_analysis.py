"""Agent ``job_analysis`` : calcul de correspondance offre / profil.

Enchaîne la re-mise en forme ORM -> dict pour le moteur de matching, l'appel du
matching LLM (``compute_llm_match``, mistral-small-latest) et la persistance
d'un ``match_result``. Le matching **exige** le LLM : pas de fallback
heuristique, une indisponibilité lève ``LLMMatchingError``.
"""

from typing import Any, Dict

from config.logger_config import setup_logging
from src.core.domain.candidate_profile import CandidateProfile
from src.core.privacy.anonymize import anonymize_cv
from src.core.scoring.llm_matcher import compute_llm_match
from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.repositories import match_result_repository
from src.infrastructure.db.session import session_scope
from src.services.profile_parser import cv_source_to_markdown

logger = setup_logging(__name__)


# --- Re-mise en forme pour le moteur de matching -----------------------------

def build_score_job(row: JobOfferModel) -> Dict[str, Any]:
    """Convertit une ligne ``job_offer`` en dict attendu par le matching LLM.

    Fournit au LLM toutes les informations utiles de l'annonce : intitulé,
    entreprise, localisation, contrat, expérience requise, formation, description
    et compétences déjà extraites à l'ingestion (``skills_extracted``).
    """
    return {
        "title": row.title or "",
        "company": row.company or "",
        "location": row.location or "",
        "contract_type": row.contract_type or "",
        "experience": row.experience or "",
        "diploma": [row.diploma] if row.diploma else [],
        "description": row.description or "",
        # Compétences déjà extraites à l'ingestion (LLM) : réutilisées telles
        # quelles pour le matching, sans re-appeler le LLM pour les extraire.
        "skills_extracted": row.skills_extracted,
    }


def build_score_profile(profile: CandidateProfile, raw_content: str = "") -> Dict[str, Any]:
    """Convertit un profil en dict attendu par le matching LLM.

    Le LLM reçoit le **CV brut anonymisé** (nom, téléphone, email, code postal
    + ville, LinkedIn retirés) — c'est lui qui lit le CV, pas un parseur. La
    structure parsée (compétences, expériences…) reste réservée à la génération
    de CV.
    """
    # Conversion HTML→Markdown avant anonymisation (alignée sur la génération
    # de CV et la lettre) : les regex d'anonymisation ne peuvent pas traverser
    # les balises HTML — un téléphone découpé par des <span> échapperait au
    # masquage et atteindrait le LLM. Pour un CV déjà Markdown, la conversion
    # est sans effet.
    markdown = cv_source_to_markdown(raw_content)
    return {
        "raw_cv": anonymize_cv(markdown, name=profile.headline),
    }


# --- Service -----------------------------------------------------------------

class JobAnalysisService:
    """Calcule et persiste les correspondances offre / profil (via LLM)."""

    def run(self, job_offer_id: int, candidate_profile_id: int) -> Dict[str, Any]:
        """Calcule le matching LLM d'une offre avec un profil et le persiste.

        Raises:
            ValueError: si l'offre ou le profil n'existent pas.
            LLMMatchingError: si le LLM est indisponible ou répond mal.
        """
        with session_scope() as session:
            job_row = session.get(JobOfferModel, job_offer_id)
            profile_row = session.get(CandidateProfileModel, candidate_profile_id)
            if job_row is None or profile_row is None:
                raise ValueError(
                    f"Offre {job_offer_id} ou profil {candidate_profile_id} introuvable"
                )

            job_dict = build_score_job(job_row)
            profile = CandidateProfile.from_row(profile_row)
            raw_content = (profile_row.cv_raw_json or {}).get("raw_content") or ""
            profile_dict = build_score_profile(profile, raw_content)

            enriched = compute_llm_match(job_dict, profile_dict)

            record = {
                "job_offer_id": job_offer_id,
                "candidate_profile_id": candidate_profile_id,
                "total_score": round(float(enriched["score"]), 2),
                "score_breakdown": enriched["score_breakdown"],
                "strengths": enriched["strengths"],
                "weaknesses": enriched["weaknesses"],
                "missing_skills": enriched["missing_skills"],
                "explanation": enriched["explanation"],
            }
            match_result_id = match_result_repository.upsert(session, record)

        logger.info(
            "Matching LLM offre=%s profil=%s score=%s",
            job_offer_id,
            candidate_profile_id,
            record["total_score"],
        )
        return {"match_result_id": match_result_id, **record}
