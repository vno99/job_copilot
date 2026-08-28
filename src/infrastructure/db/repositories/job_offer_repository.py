"""Accès à la table ``job_offer``."""

from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.models.cv_version import CVVersionModel
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.models.letter_version import LetterVersionModel
from src.infrastructure.db.models.match_result import MatchResultModel


def _fetch_existing(session: Session, rows: List[Dict]) -> Dict[Tuple[str, str], Tuple[int, Optional[str]]]:
    """Retourne {(source, source_job_id): (id, content_hash)} pour les lignes connues."""
    if not rows:
        return {}
    pairs = [(r["source"], r["source_job_id"]) for r in rows]
    stmt = select(
        JobOfferModel.source,
        JobOfferModel.source_job_id,
        JobOfferModel.id,
        JobOfferModel.content_hash,
    ).where(tuple_(JobOfferModel.source, JobOfferModel.source_job_id).in_(pairs))
    return {
        (row.source, row.source_job_id): (row.id, row.content_hash)
        for row in session.execute(stmt)
    }


def upsert_many(session: Session, rows: List[Dict]) -> Tuple[int, int, int]:
    """Upsert en masse des offres normalisées.

    Dédoublonnage sur la contrainte UNIQUE(source, source_job_id) et sur
    ``content_hash`` : une ligne dont le hash est identique est considérée
    inchangée (aucun UPDATE).

    Returns:
        Tuple (ingested, updated, unchanged).
    """
    existing = _fetch_existing(session, rows)

    to_insert: List[Dict] = []
    to_update: List[Tuple[int, Dict]] = []
    unchanged = 0

    for row in rows:
        found = existing.get((row["source"], row["source_job_id"]))
        if found is None:
            to_insert.append(row)
        else:
            row_id, current_hash = found
            if current_hash != row["content_hash"]:
                to_update.append((row_id, row))
            else:
                unchanged += 1

    ingested = 0
    if to_insert:
        stmt = pg_insert(JobOfferModel).values(to_insert)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_job_offer_source_external"
        )
        ingested = session.execute(stmt).rowcount or 0

    updated = 0
    for row_id, row in to_update:
        values = {
            k: v
            for k, v in row.items()
            if k not in ("source", "source_job_id")
        }
        session.execute(
            update(JobOfferModel)
            .where(JobOfferModel.id == row_id)
            .values(**values, updated_at=func.now())
        )
        updated += 1

    return ingested, updated, unchanged


def get_by_url(session: Session, url: str) -> Optional[JobOfferModel]:
    """Offre dont l'URL correspond exactement à ``url``, ou ``None``.

    Utilisée par l'ingestion depuis une URL (refus 409 si déjà en base) et par
    la récupération de l'id après upsert.

    Aucun index unique sur ``url`` : deux offres peuvent partager la même URL.
    On retourne la plus ancienne (``id`` croissant) plutôt que de lever
    ``MultipleResultsFound``.
    """
    stmt = (
        select(JobOfferModel)
        .where(JobOfferModel.url == url)
        .order_by(JobOfferModel.id.asc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def existing_urls(session: Session, urls: List[str]) -> set[str]:
    """URLs de ``urls`` déjà présentes dans ``job_offer`` (par colonne ``url``).

    Utilisée par l'ingestion d'une liste d'offres : on filtre les URLs déjà en
    base (indépendamment de la source — une offre scrapée Hellowork partageant
    l'URL est aussi attrapée) avant de récupérer individuellement les nouvelles.
    """
    if not urls:
        return set()
    rows = session.execute(
        select(JobOfferModel.url).where(JobOfferModel.url.in_(urls))
    )
    return {row[0] for row in rows}


def get_by_keys(
    session: Session, keys: List[Tuple[str, str]]
) -> List[JobOfferModel]:
    """Offres persistées correspondant à des clés (source, source_job_id).

    Utilisée par la route ``POST /job-offers/from-url`` pour relire les offres
    fraîchement ingérées (une seule ou une liste — plusieurs sources possibles
    pour une liste multi-domaines). L'ordre de la liste d'entrée est préservé
    (l'ordre d'extraction LLM) via un dict intermédiaire.
    """
    if not keys:
        return []
    rows = session.execute(
        select(JobOfferModel).where(
            tuple_(JobOfferModel.source, JobOfferModel.source_job_id).in_(keys)
        )
    ).scalars()
    by_key = {(row.source, row.source_job_id): row for row in rows}
    return [by_key[key] for key in keys if key in by_key]


def recent_urls(session: Session, limit: int = 50) -> List[str]:
    """URLs des ``limit`` offres les plus récemment ingérées.

    Utilisée par le DAG pour éviter de re-scraper des annonces déjà connues :
    le scraper reçoit ces URLs et saute les annonces correspondantes.
    """
    stmt = (
        select(JobOfferModel.url)
        .where(JobOfferModel.url.is_not(None))
        .order_by(JobOfferModel.ingested_at.desc())
        .limit(limit)
    )
    return [row[0] for row in session.execute(stmt)]


# Colonnes triables côté API (whitelist : jamais de nom de colonne utilisateur brut).
SORTABLE_COLUMNS = {
    "title": JobOfferModel.title,
    "company": JobOfferModel.company,
    "location": JobOfferModel.location,
    "source": JobOfferModel.source,
    "ingested_at": JobOfferModel.ingested_at,
}


def _scores_for_offers(
    session: Session, offer_ids: List[int]
) -> Dict[int, List[Tuple[MatchResultModel, Optional[str], bool, bool, bool]]]:
    """Tous les matchs (nom de profil, présence de CV, de lettre, candidature déposée).

    Les 3e et 4e éléments du tuple sont ``True`` si un CV (resp. une lettre de
    motivation) a été généré pour le couple (offre, profil) — indiqués par un
    ``cv_version`` / ``letter_version`` existant sur leur contrainte de couple
    (un seul par couple). Le 5e est ``True`` si le drapeau « candidature
    envoyée » du ``cv_version`` du couple est posé (``False`` sans CV : le LEFT
    JOIN renvoie NULL).

    Trier du meilleur score au plus faible puis du plus récent au plus ancien :
    c'est l'ordre d'affichage de la liste des scores côté interface.
    """
    if not offer_ids:
        return {}
    stmt = (
        select(
            MatchResultModel,
            CandidateProfileModel.profile_name,
            CVVersionModel.id,
            CVVersionModel.application_submitted,
            LetterVersionModel.id,
        )
        .outerjoin(
            CandidateProfileModel,
            CandidateProfileModel.id == MatchResultModel.candidate_profile_id,
        )
        # Un seul CV / une seule lettre par couple : un LEFT JOIN suffit pour
        # détecter leur présence.
        .outerjoin(
            CVVersionModel,
            (CVVersionModel.job_offer_id == MatchResultModel.job_offer_id)
            & (CVVersionModel.candidate_profile_id == MatchResultModel.candidate_profile_id),
        )
        .outerjoin(
            LetterVersionModel,
            (LetterVersionModel.job_offer_id == MatchResultModel.job_offer_id)
            & (LetterVersionModel.candidate_profile_id == MatchResultModel.candidate_profile_id),
        )
        .where(MatchResultModel.job_offer_id.in_(offer_ids))
        .order_by(
            MatchResultModel.total_score.desc(),
            MatchResultModel.created_at.desc(),
            MatchResultModel.id.desc(),
        )
    )
    grouped: Dict[
        int, List[Tuple[MatchResultModel, Optional[str], bool, bool, bool]]
    ] = {}
    for match, profile_name, cv_id, cv_submitted, letter_id in session.execute(stmt):
        grouped.setdefault(match.job_offer_id, []).append(
            (
                match,
                profile_name,
                cv_id is not None,
                letter_id is not None,
                cv_submitted is True,
            )
        )
    return grouped


def list_offers(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    company: Optional[str] = None,
    source: Optional[str] = None,
    archived: Optional[bool] = None,
    sort_by: str = "ingested_at",
    order: str = "desc",
) -> Tuple[
    int,
    List[
        Tuple[
            JobOfferModel,
            List[Tuple[MatchResultModel, Optional[str], bool, bool, bool]],
        ]
    ],
]:
    """Offres paginées.

    Args:
        company: filtre partiel (insensible à la casse) sur le nom d'entreprise.
        source: filtre partiel (insensible à la casse) sur la source d'ingestion
            (ex. ``hellowork``, nom de domaine de l'URL).
        archived: si défini, ne garde que les offres archivées (True) ou actives
            (False) ; ``None`` = pas de filtre.
        sort_by: colonne de tri parmi ``SORTABLE_COLUMNS`` (défaut ``ingested_at``).
        order: ``asc`` ou ``desc`` (défaut ``desc``).

    Returns:
        (total, rows) où chaque ligne est
        ``(JobOfferModel, [(MatchResultModel, nom_profil|None, has_cv, has_letter, application_submitted)…])``.
        Le 2e élément liste **tous** les matchs de l'offre (tous profils), du
        meilleur score au plus faible puis du plus récent au plus ancien ;
        ``has_cv`` (resp. ``has_letter``) indique qu'un CV (resp. une lettre de
        motivation) a été généré pour le couple, ``application_submitted`` que la
        candidature a été déposée pour ce couple.
    """
    if sort_by not in SORTABLE_COLUMNS:
        raise ValueError(f"tri inconnu: {sort_by!r}")
    if order not in ("asc", "desc"):
        raise ValueError(f"ordre de tri inconnu: {order!r}")

    filters = []
    if company:
        filters.append(JobOfferModel.company.ilike(f"%{company}%"))
    if source:
        filters.append(JobOfferModel.source.ilike(f"%{source}%"))
    if archived is not None:
        filters.append(JobOfferModel.archived.is_(archived))

    stmt = select(JobOfferModel)
    if filters:
        stmt = stmt.where(*filters)

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    sort_col = SORTABLE_COLUMNS[sort_by]
    direction = sort_col.asc() if order == "asc" else sort_col.desc()
    rows = session.execute(
        stmt.order_by(direction.nulls_last(), JobOfferModel.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    scores = _scores_for_offers(
        session, [row[0].id for row in rows]
    )
    return total, [
        (row[0], scores.get(row[0].id, [])) for row in rows
    ]


def set_archived(session: Session, job_offer_id: int, archived: bool) -> None:
    """Archive ou désarchive une offre.

    ``archived_at`` est renseigné à l'archivage et remis à ``None`` à la
    désarchivage ; ``updated_at`` est rafraîchi à chaque bascule.
    """
    session.execute(
        update(JobOfferModel)
        .where(JobOfferModel.id == job_offer_id)
        .values(
            archived=archived,
            archived_at=func.now() if archived else None,
            updated_at=func.now(),
        )
    )


def scores_for_offer(
    session: Session, job_offer_id: int
) -> List[Tuple[MatchResultModel, Optional[str], bool, bool, bool]]:
    """Tous les matchs d'une offre (nom de profil, CV, lettre, candidature déposée).

    Utilisé par le détail d'une offre pour lister les profils ayant déjà matché.
    """
    return _scores_for_offers(session, [job_offer_id]).get(job_offer_id, [])


def neighbors(
    session: Session, job_offer_id: int, archived: bool
) -> Tuple[Optional[int], Optional[int]]:
    """Offres précédente/suivante de ``job_offer_id`` dans le tri de la liste.

    L'ordre de la liste est ``ingested_at DESC, id DESC`` (plus récentes
    d'abord), restreint au même ensemble ``archived`` que l'offre courante.
    « Précédente » = avant dans la liste (plus récente) ; « suivante » = après
    dans la liste (plus ancienne). ``None`` aux extrémités, ou si l'offre
    n'existe pas.

    Returns:
        ``(previous_id, next_id)``.
    """
    current = session.execute(
        select(JobOfferModel.ingested_at).where(JobOfferModel.id == job_offer_id)
    ).scalar_one_or_none()
    if current is None:
        return None, None

    previous_id = session.execute(
        select(JobOfferModel.id)
        .where(
            JobOfferModel.archived.is_(archived),
            or_(
                JobOfferModel.ingested_at > current,
                and_(
                    JobOfferModel.ingested_at == current,
                    JobOfferModel.id > job_offer_id,
                ),
            ),
        )
        .order_by(JobOfferModel.ingested_at.asc(), JobOfferModel.id.asc())
        .limit(1)
    ).scalar_one_or_none()

    next_id = session.execute(
        select(JobOfferModel.id)
        .where(
            JobOfferModel.archived.is_(archived),
            or_(
                JobOfferModel.ingested_at < current,
                and_(
                    JobOfferModel.ingested_at == current,
                    JobOfferModel.id < job_offer_id,
                ),
            ),
        )
        .order_by(JobOfferModel.ingested_at.desc(), JobOfferModel.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    return previous_id, next_id
