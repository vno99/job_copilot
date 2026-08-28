"""Agent ``cv_generator`` : génération d'un CV recomposé à une offre, via le LLM.

Le LLM Mistral **recompose** le CV existant (anonymisé) en Markdown — il
réorganise, condense et reformule légèrement les informations déjà présentes
pour mettre en avant celles les plus pertinentes pour l'offre, sans modifier
les faits, le niveau de preuve, l'identité professionnelle, les responsabilités
ou le niveau d'expertise — en conservant les rubriques et la mise en forme.
Les coordonnées réelles du candidat (nom, email, téléphone,
LinkedIn) ne sont jamais transmises au LLM : elles sont capturées avant
anonymisation et réinjectées côté serveur. Un seul CV par couple (offre,
profil) : une nouvelle génération remplace l'existant (``cv_version``).

La génération se fait en **une passe** (``humanize_cv_markdown``) : la pass 1
recompose le CV sur ``CV_GENERATION_LLM`` (mistral-large-latest). La pass 2 (réécriture
« humaine », ``_rewrite_cv_human`` sur ``HUMANIZE_LLM``) est **désactivée** :
ses prompts et son code sont conservés pour un usage futur mais ne sont plus
appelés. Sans clé ou en cas de réponse invalide, ``CVGenerationError`` est levée
(→ HTTP 502), pas de fallback.
"""

from typing import Any, Dict

from config.logger_config import setup_logging
from src.core.domain.candidate_profile import CandidateProfile
from src.core.privacy.anonymize import (
    anonymize_cv,
    extract_contact_info,
    inject_contact_info,
)
from src.core.scoring.cv_generator_llm import humanize_cv_markdown
from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.repositories import (
    cv_version_repository,
    match_result_repository,
)
from src.infrastructure.db.session import session_scope
from src.services.job_analysis import build_score_job
from src.services.profile_parser import cv_source_to_markdown

logger = setup_logging(__name__)


class CvRequiresMatchError(RuntimeError):
    """Un CV ne peut être généré sans matching préalable (offre × profil).

    Mappée en HTTP 409 par l'API : il faut d'abord lancer le matching pour le
    couple. Distincte de ``ValueError`` (→ 404) pour ne pas confondre « offre
    absente » et « matching absent ».
    """


class CvGeneratorService:
    """Génère, persiste et supprime le CV recomposé à une offre (LLM, Markdown)."""

    def run(self, job_offer_id: int, candidate_profile_id: int) -> Dict[str, Any]:
        """Génère le CV pour un couple (offre, profil) et le persiste.

        Un CV existant pour le couple est **remplacé** (upsert) : un seul CV par
        couple, sans notion de version.

        Raises:
            ValueError: si l'offre ou le profil n'existent pas.
            CvRequiresMatchError: si le couple n'a pas de match_result.
            CVGenerationError: si le LLM est indisponible (clé absente, erreur
                API, réponse vide) — propagée jusqu'à l'API (HTTP 502).
        """
        with session_scope() as session:
            job_row = session.get(JobOfferModel, job_offer_id)
            if job_row is None:
                raise ValueError(f"Offre {job_offer_id} introuvable")
            mr = match_result_repository.get_by_pair(
                session, job_offer_id, candidate_profile_id
            )
            if mr is None:
                raise CvRequiresMatchError(
                    f"Pas de match_result pour offre={job_offer_id} profil={candidate_profile_id}"
                )
            profile_row = session.get(CandidateProfileModel, candidate_profile_id)
            if profile_row is None:
                raise ValueError(f"Profil {candidate_profile_id} introuvable")
            profile = CandidateProfile.from_row(profile_row)

            job_dict = build_score_job(job_row)
            match_dict = {
                "score": float(mr.total_score),
                "score_breakdown": mr.score_breakdown or {},
                "strengths": mr.strengths or [],
                "weaknesses": mr.weaknesses or [],
                "missing_skills": mr.missing_skills or [],
                "explanation": mr.explanation,
            }

            # CV brut intégral → markdown, coordonnées capturées (avant
            # anonymisation), puis CV anonymisé pour le LLM.
            raw_content = (profile_row.cv_raw_json or {}).get("raw_content") or ""
            markdown = cv_source_to_markdown(raw_content)
            contact = extract_contact_info(markdown)
            name = contact["name"] or profile.headline
            contact["name"] = name
            profile_dict = {"raw_cv": anonymize_cv(markdown, name=name)}

            generated_md = humanize_cv_markdown(job_dict, profile_dict, match_dict)
            logger.debug(f"generated_md par le LLM: {generated_md}")
            
            final_md = inject_contact_info(generated_md, contact)

            # Persistance après succès du LLM : un échec ne crée aucun
            # enregistrement. Une génération existante pour le couple est
            # remplacée (upsert) : un seul CV par couple, sans notion de version.
            record = {
                "job_offer_id": job_offer_id,
                "candidate_profile_id": candidate_profile_id,
                "match_result_id": mr.id,
                "cv_content_json": {"markdown": final_md},
                "cv_text": final_md,
                "tailoring_notes": [],
            }
            cv_id = cv_version_repository.upsert(session, record)

        logger.info(
            "CV généré (LLM) offre=%s profil=%s (id=%s)",
            job_offer_id,
            candidate_profile_id,
            cv_id,
        )
        return {"cv_id": cv_id}

    def delete(self, job_offer_id: int, candidate_profile_id: int) -> bool:
        """Supprime le CV généré d'un couple (offre, profil).

        Le matching (``match_result``) est conservé : seul le CV est retiré.

        Returns:
            True si un CV existait pour le couple (et a été supprimé), False sinon.
        """
        with session_scope() as session:
            deleted = cv_version_repository.delete_for_pair(
                session, job_offer_id, candidate_profile_id
            )

        logger.info("CV supprimé offre=%s profil=%s", job_offer_id, candidate_profile_id)
        return deleted
