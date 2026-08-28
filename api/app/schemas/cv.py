"""Schémas Pydantic des CV générés."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CVSummary(BaseModel):
    """Résumé d'un CV généré (liste)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    match_result_id: Optional[int] = None
    # Suivi « candidature envoyée » : marqué par l'utilisateur une fois la
    # candidature déposée pour le couple (offre, profil).
    application_submitted: bool = False
    created_at: datetime


class CVDetail(CVSummary):
    """Détail d'un CV généré."""

    job_offer_id: int
    candidate_profile_id: int
    cv_text: Optional[str] = None
    tailoring_notes: List[str] = []


class CVGenerateRequest(BaseModel):
    job_offer_id: int
    candidate_profile_id: Optional[int] = None


class CVGenerateResult(BaseModel):
    cv_id: int
    score: Optional[float] = None


class CvSubmittedUpdate(BaseModel):
    """Corps de ``PUT /cvs/{id}/submitted`` : l'état voulu du drapeau
    « candidature envoyée » (idempotent)."""

    submitted: bool
