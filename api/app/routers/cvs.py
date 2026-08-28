"""Routes des CV générés."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from api.app.dependencies import ensure_not_archived, get_db, resolve_profile_id
from api.app.schemas.cv import (
    CVDetail,
    CVGenerateRequest,
    CVGenerateResult,
    CVSummary,
    CvSubmittedUpdate,
)
from src.core.pdf import markdown_to_pdf
from src.core.scoring.cv_generator_llm import CVGenerationError
from src.infrastructure.db.repositories import (
    cv_version_repository,
    match_result_repository,
)
from src.services.cv_generator import CvGeneratorService, CvRequiresMatchError

router = APIRouter(tags=["cvs"])


@router.post("/cvs/generate", response_model=CVGenerateResult)
def generate_cv(body: CVGenerateRequest, db: Session = Depends(get_db)):
    """Génère le CV d'un couple (offre, profil) ; remplace l'existant.

    Un seul CV par couple : une génération existante est remplacée (upsert),
    sans notion de version.
    """
    ensure_not_archived(db, body.job_offer_id)
    pid = resolve_profile_id(db, body.candidate_profile_id)
    try:
        result = CvGeneratorService().run(body.job_offer_id, pid)
    except CvRequiresMatchError as exc:
        # La génération s'appuie sur le matching (score, forces) : il faut
        # d'abord lancer le matching pour le couple → Conflit.
        raise HTTPException(status_code=409, detail=str(exc))
    except CVGenerationError as exc:
        # La génération exige le LLM : indisponible → Bad Gateway.
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    match = match_result_repository.get_by_pair(db, body.job_offer_id, pid)
    score = float(match.total_score) if match is not None else None
    return CVGenerateResult(**result, score=score)


@router.delete("/job-offers/{job_offer_id}/cv", status_code=204)
def delete_cv(
    job_offer_id: int,
    candidate_profile_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Supprime le CV généré d'un couple (offre, profil).

    Le matching est conservé : seul le CV est retiré. ``candidate_profile_id``
    absent → profil actif. ``404`` si aucun CV n'existe pour le couple ; ``409``
    si l'offre est archivée (lecture seule).
    """
    ensure_not_archived(db, job_offer_id)
    pid = resolve_profile_id(db, candidate_profile_id)
    deleted = CvGeneratorService().delete(job_offer_id, pid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun CV généré pour l'offre {job_offer_id} et le profil {pid}",
        )
    return None


@router.get("/cvs/{cv_id}", response_model=CVDetail)
def get_cv(cv_id: int, db: Session = Depends(get_db)):
    """Détail d'un CV généré (``cv_text`` = Markdown généré)."""
    row = cv_version_repository.get_by_id(db, cv_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"CV {cv_id} introuvable")
    return row


@router.put("/cvs/{cv_id}/submitted", response_model=CVSummary)
def set_cv_submitted(
    cv_id: int, body: CvSubmittedUpdate, db: Session = Depends(get_db)
):
    """Bascule le drapeau « candidature envoyée » d'un CV généré.

    Suivi utilisateur pour un couple (offre, profil) une fois la candidature
    déposée : ``submitted`` est l'état voulu (idempotent). Autorisé sur une
    offre archivée (drapeau de suivi, pas une mutation de document). ``404``
    si le CV n'existe pas.
    """
    row = cv_version_repository.set_application_submitted(db, cv_id, body.submitted)
    if row is None:
        raise HTTPException(status_code=404, detail=f"CV {cv_id} introuvable")
    return row


@router.get("/cvs/{cv_id}/pdf")
def get_cv_pdf(cv_id: int, db: Session = Depends(get_db)):
    """PDF téléchargeable du CV généré (Markdown converti côté serveur).

    ``Content-Disposition: attachment`` force le téléchargement d'un fichier
    ``cv_{cv_id}.pdf`` ; ``404`` si le CV n'existe pas.
    """
    row = cv_version_repository.get_by_id(db, cv_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"CV {cv_id} introuvable")
    pdf = markdown_to_pdf(row.cv_text or "")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cv_{cv_id}.pdf"'},
    )
