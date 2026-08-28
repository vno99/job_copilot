"""Schémas Pydantic du profil candidat."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileOut(BaseModel):
    """Profil complet, tel qu'exposé par l'API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_name: str
    headline: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = []
    experiences: List[Any] = []
    education: List[str] = []
    source_path: str = ""
    raw_content: str = ""
    raw_content_markdown: str = ""
    is_active: bool = False
    created_at: datetime
    updated_at: datetime


class ProfileRename(BaseModel):
    """Corps du renommage d'un profil."""

    profile_name: str = Field(min_length=1, max_length=200)

    @field_validator("profile_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("profile_name ne peut pas être vide")
        return value


class ProfileSummary(BaseModel):
    """Entrée de la liste des profils."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
