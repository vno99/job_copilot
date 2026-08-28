"""Schémas Pydantic des lettres de motivation générées."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LetterSummary(BaseModel):
    """Résumé d'une lettre de motivation générée (liste)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    match_result_id: Optional[int] = None
    created_at: datetime


class LetterDetail(LetterSummary):
    """Détail d'une lettre de motivation générée."""

    job_offer_id: int
    candidate_profile_id: int
    letter_text: Optional[str] = None


class LetterGenerateRequest(BaseModel):
    job_offer_id: int
    candidate_profile_id: Optional[int] = None


class LetterGenerateResult(BaseModel):
    letter_id: int
    score: Optional[float] = None
