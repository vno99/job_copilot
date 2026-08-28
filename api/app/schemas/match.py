"""Schémas Pydantic du matching offre/profil."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class MatchResultOut(BaseModel):
    """Résultat de matching complet."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_offer_id: int
    candidate_profile_id: int
    total_score: float
    score_breakdown: Dict[str, float]
    strengths: List[str] = []
    weaknesses: List[str] = []
    missing_skills: List[str] = []
    explanation: Optional[str] = None
    created_at: datetime


class MatchRunRequest(BaseModel):
    job_offer_id: int
    candidate_profile_id: Optional[int] = None


