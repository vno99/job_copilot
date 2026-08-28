"""Routes des lettres de motivation générées."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.app.dependencies import ensure_not_archived, get_db, resolve_profile_id
from api.app.schemas.letter import (
    LetterDetail,
    LetterGenerateRequest,
    LetterGenerateResult,
)
from src.core.scoring.letter_generator_llm import LetterGenerationError
from src.infrastructure.db.repositories import (
    letter_version_repository,
    match_result_repository,
)
from src.services.letter_generator import (
    LetterGeneratorService,
    LetterRequiresMatchError,
)

router = APIRouter(tags=["letters"])


@router.post("/letters/generate", response_model=LetterGenerateResult)
def generate_letter(body: LetterGenerateRequest, db: Session = Depends(get_db)):
    """Génère la lettre de motivation d'un couple (offre, profil) ; remplace l'existante.

    Une seule lettre par couple : une génération existante est remplacée
    (upsert), sans notion de version.
    """
    ensure_not_archived(db, body.job_offer_id)
    pid = resolve_profile_id(db, body.candidate_profile_id)
    try:
        result = LetterGeneratorService().run(body.job_offer_id, pid)
    except LetterRequiresMatchError as exc:
        # La lettre s'appuie sur le matching (score, forces) : il faut d'abord
        # lancer le matching pour le couple → Conflit.
        raise HTTPException(status_code=409, detail=str(exc))
    except LetterGenerationError as exc:
        # La génération exige le LLM : indisponible → Bad Gateway.
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    match = match_result_repository.get_by_pair(db, body.job_offer_id, pid)
    score = float(match.total_score) if match is not None else None
    return LetterGenerateResult(**result, score=score)


@router.delete("/job-offers/{job_offer_id}/letter", status_code=204)
def delete_letter(
    job_offer_id: int,
    candidate_profile_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Supprime la lettre générée d'un couple (offre, profil).

    Le matching est conservé : seule la lettre est retirée.
    ``candidate_profile_id`` absent → profil actif. ``404`` si aucune lettre
    n'existe pour le couple ; ``409`` si l'offre est archivée (lecture seule).
    """
    ensure_not_archived(db, job_offer_id)
    pid = resolve_profile_id(db, candidate_profile_id)
    deleted = LetterGeneratorService().delete(job_offer_id, pid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Aucune lettre de motivation pour l'offre {job_offer_id} "
                f"et le profil {pid}"
            ),
        )
    return None


@router.get("/letters/{letter_id}", response_model=LetterDetail)
def get_letter(letter_id: int, db: Session = Depends(get_db)):
    """Détail d'une lettre générée (``letter_text`` = Markdown généré)."""
    row = letter_version_repository.get_by_id(db, letter_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Lettre {letter_id} introuvable")
    return row
