"""Agent ``letter_generator`` : génération d'une lettre de motivation via le LLM.

Le LLM Mistral rédige une lettre de motivation pour un couple (offre, profil), à
partir de l'offre et du CV du candidat. Le CV est le **CV recomposé généré**
(``cv_version.cv_text``) s'il existe pour le couple, sinon le **CV brut du
profil**. Le contenu envoyé au LLM est **anonymisé** (nom, email, téléphone,
code postal + ville, LinkedIn) ; aucune coordonnée n'est réinjectée : la lettre
générée reste **anonyme** et se termine par la formule de politesse du LLM. Une
seule lettre par couple (offre, profil) : une nouvelle génération remplace
l'existante (``letter_version``).

La génération se fait en **deux passes** (``humanize_letter_markdown``) : la
pass 1 rédige la lettre (comportement historique), puis une passe 2 **best-effort**
la réécrit systématiquement avec un style humain. En cas d'échec de la pass 2,
la lettre de la pass 1 est conservée.
"""

from typing import Any, Dict

from config.logger_config import setup_logging
from src.core.domain.candidate_profile import CandidateProfile
from src.core.privacy.anonymize import (
    anonymize_cv,
    clean_letter_markdown,
    extract_contact_info,
)
from src.core.scoring.letter_generator_llm import humanize_letter_markdown
from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.repositories import (
    cv_version_repository,
    letter_version_repository,
    match_result_repository,
)
from src.infrastructure.db.session import session_scope
from src.services.job_analysis import build_score_job
from src.services.profile_parser import cv_source_to_markdown

logger = setup_logging(__name__)


class LetterRequiresMatchError(RuntimeError):
    """Une lettre ne peut être générée sans matching préalable (offre × profil).

    Mappée en HTTP 409 par l'API : il faut d'abord lancer le matching pour le
    couple. Distincte de ``ValueError`` (→ 404) pour ne pas confondre « offre
    absente » et « matching absent ».
    """


class LetterGeneratorService:
    """Génère, persiste et supprime la lettre de motivation d'un couple (offre, profil)."""

    def run(self, job_offer_id: int, candidate_profile_id: int) -> Dict[str, Any]:
        """Génère la lettre pour un couple (offre, profil) et la persiste.

        Source candidat : le CV généré (``cv_version.cv_text``) s'il existe pour
        le couple, sinon le CV brut du profil (``cv_raw_json.raw_content``). Le
        contenu est anonymisé avant envoi au LLM ; la lettre générée reste
        **anonyme** (aucune coordonnée réelle n'est réinjectée).

        Raises:
            ValueError: si l'offre, le profil ou le match_result n'existent pas.
            LetterGenerationError: si le LLM est indisponible (clé absente,
                erreur API, réponse vide) — propagée jusqu'à l'API (HTTP 502).
        """
        with session_scope() as session:
            job_row = session.get(JobOfferModel, job_offer_id)
            if job_row is None:
                raise ValueError(f"Offre {job_offer_id} introuvable")
            mr = match_result_repository.get_by_pair(
                session, job_offer_id, candidate_profile_id
            )
            if mr is None:
                raise LetterRequiresMatchError(
                    f"Pas de match pour offre={job_offer_id} profil={candidate_profile_id}"
                )
            profile_row = session.get(CandidateProfileModel, candidate_profile_id)
            if profile_row is None:
                raise ValueError(f"Profil {candidate_profile_id} introuvable")
            profile = CandidateProfile.from_row(profile_row)

            job_dict = build_score_job(job_row)

            # Source candidat : CV généré si présent pour le couple, sinon CV
            # brut du profil.
            existing_cv = cv_version_repository.list_for_offer(
                session, job_offer_id, candidate_profile_id
            )
            if existing_cv:
                markdown = existing_cv[0].cv_text or ""
            else:
                raw_content = (profile_row.cv_raw_json or {}).get("raw_content") or ""
                markdown = cv_source_to_markdown(raw_content)

            # Nom du candidat (jamais transmis au LLM) et contenu anonymisé pour
            # le LLM. La lettre générée reste anonyme : clean_letter_markdown
            # retire l'identité et les placeholders résiduels, aucune coordonnée
            # réelle n'est réinjectée.
            name = extract_contact_info(markdown)["name"] or profile.headline
            profile_dict = {"raw_cv": anonymize_cv(markdown, name=name)}

            generated_md = humanize_letter_markdown(job_dict, profile_dict)
            logger.debug(f"generated letter par le LLM: {generated_md}")

            final_md = clean_letter_markdown(generated_md, name)

            # Persistance après succès du LLM : un échec ne crée aucun
            # enregistrement. Une lettre existante pour le couple est remplacée
            # (upsert) : une seule lettre par couple, sans notion de version.
            record = {
                "job_offer_id": job_offer_id,
                "candidate_profile_id": candidate_profile_id,
                "match_result_id": mr.id,
                "letter_content_json": {"markdown": final_md},
                "letter_text": final_md,
            }
            letter_id = letter_version_repository.upsert(session, record)

        logger.info(
            "Lettre générée (LLM) offre=%s profil=%s (id=%s)",
            job_offer_id,
            candidate_profile_id,
            letter_id,
        )
        return {"letter_id": letter_id}

    def delete(self, job_offer_id: int, candidate_profile_id: int) -> bool:
        """Supprime la lettre générée d'un couple (offre, profil).

        Le matching (``match_result``) est conservé : seule la lettre est retirée.

        Returns:
            True si une lettre existait pour le couple (et a été supprimée),
            False sinon.
        """
        with session_scope() as session:
            deleted = letter_version_repository.delete_for_pair(
                session, job_offer_id, candidate_profile_id
            )

        logger.info(
            "Lettre supprimée offre=%s profil=%s",
            job_offer_id,
            candidate_profile_id,
        )
        return deleted
