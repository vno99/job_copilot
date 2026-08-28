"""Routes du profil candidat : liste, upload, activation, renommage,
désactivation, lecture."""

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.app.dependencies import get_db
from api.app.schemas.profile import ProfileOut, ProfileRename, ProfileSummary
from src.core.domain.candidate_profile import CandidateProfile
from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.repositories import candidate_profile_repository
from src.services.profile_parser import ProfileParserService, cv_source_to_markdown

router = APIRouter(tags=["profile"])

# Taille maximale d'un CV uploadé (multipart) : 5 Mo — un CV Markdown/HTML est
# rarement volumineux. Borne la lecture en mémoire d'une API sans authentification.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def profile_payload(row: CandidateProfileModel) -> dict:
    """Sérialise une ligne ORM en dict complet (``cv_raw_json`` inclus)."""
    p = CandidateProfile.from_row(row)
    meta = row.cv_raw_json or {}
    raw = meta.get("raw_content") or ""
    return {
        "id": row.id,
        "profile_name": row.profile_name,
        "headline": p.headline or None,
        "summary": p.summary or None,
        "skills": p.skills,
        "experiences": p.experiences,
        "education": p.education,
        "source_path": p.source_path,
        "raw_content": raw,
        "raw_content_markdown": cv_source_to_markdown(raw),
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/profiles", response_model=List[ProfileSummary])
def list_profiles(db: Session = Depends(get_db)) -> List[ProfileSummary]:
    """Liste les profils en base (du plus récent au plus ancien)."""
    rows = candidate_profile_repository.list_all(db)
    return [ProfileSummary.model_validate(r) for r in rows]


@router.post("/profiles", response_model=ProfileOut, status_code=201)
async def upload_profile(
    file: UploadFile = File(...),
    profile_name: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    """Upload d'un CV (Markdown/HTML) → nouveau ``candidate_profile``."""
    # Lecture bornée : un upload volumineux ne doit pas épuiser la mémoire du
    # worker (API sans authentification → déni de service possible).
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)",
        )
    content = raw.decode("utf-8", errors="replace")
    # Nom du profil : mêmes contraintes que le renommage (PATCH) — trimé,
    # 1–200 caractères, non réduit à des espaces → 422. Vide/absent → généré.
    if profile_name is not None:
        profile_name = profile_name.strip() or None
        if profile_name is not None and len(profile_name) > 200:
            raise HTTPException(
                status_code=422,
                detail="Le nom du profil doit faire au plus 200 caractères",
            )
    # Nom fourni : refus 409 dès le contrôle préalable (le nom est unique).
    if profile_name:
        existing = candidate_profile_repository.get_by_name(db, profile_name)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Le nom '{profile_name}' est déjà utilisé par un autre profil",
            )
    try:
        profile_id = ProfileParserService().run_from_content(
            content, profile_name=profile_name, filename=file.filename
        )
    except IntegrityError:
        # Course TOCTOU entre le contrôle préalable et l'insertion (nom pris au
        # même moment, ou deux uploads simultanés sans nom) : 409 au lieu d'un 500.
        raise HTTPException(
            status_code=409,
            detail=(
                "Conflit lors de la création du profil : ce nom est déjà utilisé, "
                "ou un profil concurrent a été créé au même instant"
            ),
        )
    row = db.get(CandidateProfileModel, profile_id)
    return profile_payload(row)


@router.get("/profile", response_model=ProfileOut)
def get_active_profile(db: Session = Depends(get_db)) -> dict:
    """Profil actif (`is_active = true`)."""
    row = candidate_profile_repository.get_active(db)
    if row is None:
        raise HTTPException(status_code=404, detail="Aucun profil actif")
    return profile_payload(row)


@router.get("/profile/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)) -> dict:
    """Profil par id."""
    row = db.get(CandidateProfileModel, profile_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Profil {profile_id} introuvable"
        )
    return profile_payload(row)


@router.put("/profiles/{profile_id}/activate", response_model=ProfileOut)
def activate_profile(profile_id: int, db: Session = Depends(get_db)) -> dict:
    """Rend le profil actif (désactive les autres)."""
    if not candidate_profile_repository.set_active(db, profile_id):
        raise HTTPException(
            status_code=404, detail=f"Profil {profile_id} introuvable"
        )
    row = db.get(CandidateProfileModel, profile_id)
    return profile_payload(row)


@router.put("/profiles/{profile_id}/deactivate", response_model=ProfileOut)
def deactivate_profile(profile_id: int, db: Session = Depends(get_db)) -> dict:
    """Désactive le profil (``is_active = false``), sans toucher aux autres.

    Le **profil actif ne peut pas être désactivé** (``409``) : il faut activer un
    autre profil pour lui retirer son statut actif.
    """
    active = candidate_profile_repository.get_active(db)
    if active is not None and active.id == profile_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Le profil actif ne peut pas être désactivé : "
                "activez d'abord un autre profil"
            ),
        )
    if not candidate_profile_repository.set_active(db, profile_id, active=False):
        raise HTTPException(
            status_code=404, detail=f"Profil {profile_id} introuvable"
        )
    row = db.get(CandidateProfileModel, profile_id)
    return profile_payload(row)


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
def rename_profile(
    profile_id: int, body: ProfileRename, db: Session = Depends(get_db)
) -> dict:
    """Renomme un profil (le nom est unique)."""
    if db.get(CandidateProfileModel, profile_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Profil {profile_id} introuvable"
        )
    existing = candidate_profile_repository.get_by_name(db, body.profile_name)
    if existing is not None and existing.id != profile_id:
        raise HTTPException(
            status_code=409,
            detail=f"Le nom '{body.profile_name}' est déjà utilisé par un autre profil",
        )
    row = candidate_profile_repository.rename(db, profile_id, body.profile_name)
    return profile_payload(row)
