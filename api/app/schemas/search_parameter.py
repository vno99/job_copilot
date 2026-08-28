"""Schémas Pydantic des paramètres de recherche."""

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_required(value: str, field_name: str) -> str:
    """Trim + rejet si vide (miroir de ``ProfileRename.strip_name``)."""
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} ne peut pas être vide")
    return value


def _validate_url(value: str) -> str:
    """Exige un schéma ``http``/``https`` et un hostname non vide (422).

    ``str`` simple (pas ``HttpUrl``) pour garder la maîtrise du message
    d'erreur, comme ``URLOfferRequest``.
    """
    value = value.strip()
    if not value:
        raise ValueError("url ne peut pas être vide")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(
            "URL invalide : seuls les schémas http/https sont autorisés"
        )
    return value


class SearchParameterOut(BaseModel):
    """Paramètre de recherche, tel qu'exposé par l'API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source: str
    url: str
    max_offers: int
    # Actif = pris en compte par l'agent de recherche (activé à la création).
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SearchParameterCreate(BaseModel):
    """Corps de la création d'un paramètre de recherche."""

    title: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1)
    # Nombre maximal d'offres nouvelles ingérées par l'agent de recherche pour
    # une URL de liste (slider 1 → 20 de l'interface, défaut 5).
    max_offers: int = Field(5, ge=1, le=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return _validate_required(value, "title")

    @field_validator("source")
    @classmethod
    def strip_source(cls, value: str) -> str:
        return _validate_required(value, "source")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_url(value)


class SearchParameterUpdate(SearchParameterCreate):
    """Corps de la mise à jour (PATCH complet : les trois champs sont requis)."""
