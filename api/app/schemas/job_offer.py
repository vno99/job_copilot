"""Schémas Pydantic des offres d'emploi."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from api.app.schemas.cv import CVSummary
from api.app.schemas.letter import LetterSummary
from api.app.schemas.match import MatchResultOut


class JobOfferScore(BaseModel):
    """Score d'une offre pour un profil donné."""

    candidate_profile_id: int
    profile_name: Optional[str] = None
    total_score: float
    created_at: datetime
    # Indicateurs d'artefacts générés pour le couple (offre, profil) : un CV
    # existe-t-il ? une lettre de motivation ? (affiches dans la cellule score).
    has_cv: bool = False
    has_letter: bool = False
    # Suivi « candidature envoyée » pour le couple (drapeau du cv_version) :
    # la candidature a été déposée pour cette offre avec ce profil.
    application_submitted: bool = False


class JobOfferListItem(BaseModel):
    """Entrée de la liste des offres.

    ``scores`` liste tous les matchs de l'offre, du meilleur score au plus
    faible puis du plus récent au plus ancien ; une offre est matchée dès
    qu'elle a au moins un score.
    """

    id: int
    # Source d'ingestion de l'offre (ex. `hellowork`, nom de domaine de l'URL).
    source: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    contract_type: Optional[str] = None
    published_date: Optional[date] = None
    url: str
    ingested_at: datetime
    archived: bool = False
    scores: List[JobOfferScore] = []


class JobOfferList(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[JobOfferListItem]


class JobOfferDetail(BaseModel):
    """Détail d'une offre, avec son match (profil ciblé ou actif), ses CV et ses lettres.

    ``candidate_profile_id`` : profil ayant servi au calcul de ``match`` et aux
    listes ``cvs`` / ``letters`` (celui demandé via le query param, sinon le
    profil actif). ``scores`` liste les profils ayant déjà matché avec l'offre
    (tous profils), du meilleur score au plus faible : c'est la source du menu
    des candidats d'une offre archivée.
    """

    id: int
    source: str
    source_job_id: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    contract_type: Optional[str] = None
    published_date: Optional[date] = None
    experience: Optional[str] = None
    diploma: Optional[str] = None
    description: Optional[str] = None
    skills_extracted: Optional[dict] = None
    url: str
    ingested_at: datetime
    archived: bool = False
    archived_at: Optional[datetime] = None
    candidate_profile_id: Optional[int] = None
    previous_offer_id: Optional[int] = None
    next_offer_id: Optional[int] = None
    match: Optional[MatchResultOut] = None
    scores: List[JobOfferScore] = []
    cvs: List[CVSummary] = []
    letters: List[LetterSummary] = []


class ArchiveUpdate(BaseModel):
    """Corps de ``PUT /job-offers/{id}/archived`` : archiver ou désarchiver."""

    archived: bool


class ArchiveResult(BaseModel):
    """Retour de la bascule d'archivage."""

    job_offer_id: int
    archived: bool
    archived_at: Optional[datetime] = None


class URLOfferRequest(BaseModel):
    """Corps de ``POST /job-offers/from-url``.

    ``url`` est une ``str`` simple (pas ``HttpUrl``) : la validation sémantique
    (schéma http/https, hostname) est faite par ``URLScraper.normalize_url``,
    ce qui garde le contrôle du message d'erreur (HTTP 422). ``max_offers`` borne
    le nombre maximal d'offres **nouvelles** à ingérer pour une liste (slider
    1 → 20 de l'interface, défaut 5 ; ignoré quand ``source`` est fourni).
    ``source`` (optionnel) : contenu de la page collé par l'utilisateur (HTML du
    code source ou texte). Présent, il **remplace le fetch Playwright**
    (``run_from_source``, offre unique) : l'URL n'est **jamais récupérée**, elle
    reste la clé de dédoublonnage (409 si déjà en base) et la source d'ingestion
    (domaine). Absent → comportement historique (fetch + ``run``, offre unique
    ou liste). Sa taille est bornée côté route (HTTP 413).
    """

    url: str
    max_offers: int = Field(5, ge=1, le=20)
    source: Optional[str] = None


class URLIngestResult(BaseModel):
    """Retour de ``POST /job-offers/from-url`` : les offres persistées et les
    compteurs d'ingestion.

    ``added`` = offres nouvellement insérées ; ``already_present`` = offres déjà
    en base — pour une liste, les URLs extraites déjà présentes (ignorées, non
    mises à jour) ; pour une offre unique, 0 (un doublon répond 409). ``offers``
    liste les offres persistées dans l'ordre d'extraction.
    """

    offers: List[JobOfferListItem]
    added: int
    already_present: int
