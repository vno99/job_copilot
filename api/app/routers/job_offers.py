"""Routes des offres d'emploi."""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.app.dependencies import (
    active_profile_id_or_none,
    get_db,
)
from api.app.schemas.job_offer import (
    ArchiveResult,
    ArchiveUpdate,
    JobOfferDetail,
    JobOfferList,
    JobOfferListItem,
    JobOfferScore,
    URLIngestResult,
    URLOfferRequest,
)
from src.core.scoring.url_offer_extractor import LLMExtractionError, URLScrapingError
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.repositories import (
    cv_version_repository,
    job_offer_repository,
    letter_version_repository,
    match_result_repository,
)
from src.services.url_job_ingestor import (
    SOURCE_MAX_CHARS,
    URLOfferDuplicateError,
    URLJobIngestorService,
)

router = APIRouter(tags=["job-offers"])


def _score_items(scores) -> List[JobOfferScore]:
    """Mapping (MatchResultModel, nom_profil, has_cv, has_letter, application_submitted) → JobOfferScore."""
    return [
        JobOfferScore(
            candidate_profile_id=m.candidate_profile_id,
            profile_name=profile_name,
            total_score=float(m.total_score),
            created_at=m.created_at,
            has_cv=has_cv,
            has_letter=has_letter,
            application_submitted=application_submitted,
        )
        for m, profile_name, has_cv, has_letter, application_submitted in scores
    ]


def _list_item(job, scores) -> JobOfferListItem:
    return JobOfferListItem(
        id=job.id,
        source=job.source,
        title=job.title,
        company=job.company,
        location=job.location,
        contract_type=job.contract_type,
        published_date=job.published_date,
        url=job.url,
        ingested_at=job.ingested_at,
        archived=job.archived,
        scores=_score_items(scores),
    )


def _refetch_ingested(db: Session, result) -> URLIngestResult:
    """Relit les offres persistées par leurs clés de dédoublonnage et construit
    la réponse d'ingestion (offre unique, liste, ou contenu collé via
    ``source``)."""
    offers = job_offer_repository.get_by_keys(db, result.keys)
    if len(offers) != len(result.keys):
        # Upsert réussi mais refetch incomplet : inattendu, signaler en 500.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Erreur de relecture des offres ingérées "
                f"({len(offers)}/{len(result.keys)})"
            ),
        )
    scores = job_offer_repository._scores_for_offers(
        db, [offer.id for offer in offers]
    )
    return URLIngestResult(
        offers=[_list_item(offer, scores.get(offer.id, [])) for offer in offers],
        added=result.added,
        already_present=result.already_present,
    )


_SortBy = Literal["title", "company", "location", "source", "ingested_at"]


@router.get("/job-offers", response_model=JobOfferList)
def list_job_offers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    company: Optional[str] = None,
    source: Optional[str] = None,
    archived: bool = Query(False),
    sort_by: _SortBy = "ingested_at",
    order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
):
    """Liste paginée des offres.

    Chaque item expose ``source`` et ``scores`` (tous les matchs de l'offre,
    tous profils confondus) ; une offre est matchée dès qu'elle a au moins un
    score. ``archived`` restreint aux offres archivées (``true``) ou actives
    (``false``, défaut). ``company`` (resp. ``source``) filtre partiellement
    (insensible à la casse) sur le nom d'entreprise (resp. la source
    d'ingestion). Le tri est serveur sur ``sort_by`` (parmi ``title``,
    ``company``, ``location``, ``source``, ``ingested_at``) dans le sens
    ``order`` ; défaut : ``ingested_at`` décroissant (plus récentes d'abord).
    """
    total, rows = job_offer_repository.list_offers(
        session=db,
        limit=limit,
        offset=offset,
        company=company,
        source=source,
        archived=archived,
        sort_by=sort_by,
        order=order,
    )
    return JobOfferList(
        total=total,
        limit=limit,
        offset=offset,
        items=[_list_item(job, scores) for job, scores in rows],
    )


@router.get("/job-offers/{job_offer_id}", response_model=JobOfferDetail)
def get_job_offer(
    job_offer_id: int,
    candidate_profile_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Détail d'une offre, avec son match (profil choisi ou actif), ses CV et ses lettres.

    ``candidate_profile_id`` : profil ciblé ; absent → profil actif.
    """
    job = db.get(JobOfferModel, job_offer_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Offre {job_offer_id} introuvable"
        )
    pid = (
        candidate_profile_id
        if candidate_profile_id is not None
        else active_profile_id_or_none(db)
    )
    match = None
    cvs = []
    letters = []
    if pid is not None:
        match = match_result_repository.get_by_pair(db, job_offer_id, pid)
        cvs = cv_version_repository.list_for_offer(db, job_offer_id, pid)
        letters = letter_version_repository.list_for_offer(db, job_offer_id, pid)
    previous_offer_id, next_offer_id = job_offer_repository.neighbors(
        db, job_offer_id, job.archived
    )
    return JobOfferDetail(
        id=job.id,
        source=job.source,
        source_job_id=job.source_job_id,
        title=job.title,
        company=job.company,
        location=job.location,
        contract_type=job.contract_type,
        published_date=job.published_date,
        experience=job.experience,
        diploma=job.diploma,
        description=job.description,
        skills_extracted=job.skills_extracted,
        url=job.url,
        ingested_at=job.ingested_at,
        archived=job.archived,
        archived_at=job.archived_at,
        candidate_profile_id=pid,
        match=match,
        scores=_score_items(job_offer_repository.scores_for_offer(db, job_offer_id)),
        cvs=cvs,
        letters=letters,
        previous_offer_id=previous_offer_id,
        next_offer_id=next_offer_id,
    )


@router.put("/job-offers/{job_offer_id}/archived", response_model=ArchiveResult)
def update_archived(
    job_offer_id: int,
    body: ArchiveUpdate,
    db: Session = Depends(get_db),
):
    """Archive ou désarchive une offre (lecture seule une fois archivée)."""
    job = db.get(JobOfferModel, job_offer_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Offre {job_offer_id} introuvable"
        )
    job_offer_repository.set_archived(db, job_offer_id, body.archived)
    db.refresh(job)  # relit archived / archived_at définis par l'UPDATE
    return ArchiveResult(
        job_offer_id=job_offer_id,
        archived=body.archived,
        archived_at=job.archived_at,
    )


@router.post("/job-offers/from-url", status_code=201, response_model=URLIngestResult)
def create_offer_from_url(body: URLOfferRequest, db: Session = Depends(get_db)):
    """Ingère des offres depuis une URL, ou depuis le contenu de sa page collé.

    **URL seule** (``source`` absent) : récupération de la page via Playwright
    puis classification par le LLM (``mistral-small-latest``). **Offre unique** :
    le contenu est extrait directement (409 si déjà en base). **Liste d'offres** :
    le LLM extrait les URLs des offres, on écarte celles déjà en base (colonne
    ``url``), puis on récupère individuellement jusqu'à ``body.max_offers`` offres
    **nouvelles** (fetch Playwright + extraction mono-offre). Les offres déjà
    présentes sont comptées dans ``already_present`` et ne sont pas mises à jour.
    Les offres ingérées passent par le pipeline existant (matching / CV / lettre).

    **``source`` fourni** (contenu collé par l'utilisateur) : le contenu
    **remplace le fetch Playwright** — converti en texte puis extrait par le LLM
    (``extract_offer``, **mono-offre** — un source de liste répond 422). L'URL
    fournie n'est **jamais récupérée** : clé de dédoublonnage (409 si déjà en
    base) et source d'ingestion (domaine). Débloque les sites dont la page bloque
    le navigateur headless (anti-bot) **sans contournement automatisé** — c'est
    l'utilisateur qui colle le contenu lui-même. Le ``source`` est borné
    (``SOURCE_MAX_CHARS``) : au-delà, HTTP 413.
    """
    if body.source is not None and len(body.source) > SOURCE_MAX_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Source trop volumineux (max {SOURCE_MAX_CHARS} caractères)",
        )
    try:
        if body.source:
            result = URLJobIngestorService().run_from_source(body.url, body.source)
        else:
            result = URLJobIngestorService().run(body.url, body.max_offers)
    except URLOfferDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LLMExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except URLScrapingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _refetch_ingested(db, result)
