"""Routes du matching offre/profil."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.app.dependencies import ensure_not_archived, get_db, resolve_profile_id
from api.app.schemas.match import (
    MatchResultOut,
    MatchRunRequest,
)
from src.core.scoring.llm_matcher import LLMMatchingError
from src.infrastructure.db.repositories import match_result_repository
from src.services.job_analysis import JobAnalysisService

router = APIRouter(tags=["matching"])


@router.post("/matching/run", response_model=MatchResultOut)
def run_match(body: MatchRunRequest, db: Session = Depends(get_db)):
    """Calcule et persiste le matching d'une offre contre un profil."""
    ensure_not_archived(db, body.job_offer_id)
    pid = resolve_profile_id(db, body.candidate_profile_id)
    try:
        JobAnalysisService().run(body.job_offer_id, pid)
    except LLMMatchingError as exc:
        # Le matching exige le LLM : indisponible → Bad Gateway.
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    match = match_result_repository.get_by_pair(db, body.job_offer_id, pid)
    return match


@router.delete("/matching/{job_offer_id}", status_code=204)
def delete_match(
    job_offer_id: int,
    candidate_profile_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Supprime le matching d'un couple (offre, profil) **et ses CV associés**.

    L'offre redevient vierge pour ce profil (plus de score, plus de version de
    CV). ``candidate_profile_id`` absent → profil actif. ``404`` si l'offre est
    introuvable ou si aucun matching n'existe pour le couple ; ``409`` si
    l'offre est archivée (lecture seule).
    """
    ensure_not_archived(db, job_offer_id)
    pid = resolve_profile_id(db, candidate_profile_id)
    deleted = match_result_repository.delete_for_pair(db, job_offer_id, pid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun matching pour l'offre {job_offer_id} et le profil {pid}",
        )
    return None
