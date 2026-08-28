"""Routes des recherches sauvegardées : liste, création, mise à jour,
suppression, exécution de l'agent de recherche (globale et unitaire)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.app.dependencies import get_db
from api.app.schemas.search_parameter import (
    SearchParameterCreate,
    SearchParameterOut,
    SearchParameterUpdate,
)
from src.infrastructure.db.models.search_parameters import SearchParameterModel
from src.infrastructure.db.repositories import search_parameters_repository
from src.services.search_parameters_agent import SearchParametersAgentService

router = APIRouter(tags=["search-parameters"])


@router.post("/search-parameters/run")
def run_search_agent() -> Dict[str, Any]:
    """Exécute l'agent de recherche immédiatement (même pipeline que le DAG).

    Lit ``search_parameters`` et ingère les offres de chaque URL **active** via
    ``URLJobIngestorService.run`` — le matching/CV/lettre sont immédiatement
    disponibles. Synchrone : la réponse est le résumé d'ingestion
    (``added_offers``, ``already_present``, échecs par catégorie). Une recherche
    en échec n'interrompt pas le run.
    """
    return SearchParametersAgentService().run()


@router.post("/search-parameters/{search_parameter_id}/run")
def run_search_parameter(search_parameter_id: int) -> Dict[str, Any]:
    """Exécute **une** recherche sauvegardée, qu'elle soit active ou non
    (lancement unitaire depuis l'UI — test ponctuel, le statut est inchangé).

    Même pipeline que ``run_search_agent`` pour une seule ligne : résumé
    d'ingestion (``parameters[0]`` porte titre/source/URL/max_offers et le
    statut). 404 si l'id est inconnu.
    """
    try:
        return SearchParametersAgentService().run_parameter_by_id(
            search_parameter_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/search-parameters", response_model=List[SearchParameterOut])
def list_search_parameters(
    db: Session = Depends(get_db),
) -> List[SearchParameterOut]:
    """Liste les paramètres de recherche (du plus récent au plus ancien)."""
    rows = search_parameters_repository.list_all(db)
    return [SearchParameterOut.model_validate(r) for r in rows]


@router.post("/search-parameters", response_model=SearchParameterOut, status_code=201)
def create_search_parameter(
    body: SearchParameterCreate, db: Session = Depends(get_db)
) -> SearchParameterOut:
    """Crée un paramètre de recherche (l'URL est unique)."""
    existing = search_parameters_repository.get_by_url(db, body.url)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"L'URL '{body.url}' est déjà utilisée par « {existing.title} »",
        )
    try:
        param_id = search_parameters_repository.insert(db, body.model_dump())
    except IntegrityError:
        # Course TOCTOU entre le contrôle préalable et l'insertion (URL prise au
        # même moment) : 409 au lieu d'un 500.
        raise HTTPException(
            status_code=409,
            detail=f"L'URL '{body.url}' est déjà utilisée par un autre paramètre",
        )
    row = db.get(SearchParameterModel, param_id)
    return SearchParameterOut.model_validate(row)


@router.patch("/search-parameters/{search_parameter_id}", response_model=SearchParameterOut)
def update_search_parameter(
    search_parameter_id: int,
    body: SearchParameterUpdate,
    db: Session = Depends(get_db),
) -> SearchParameterOut:
    """Met à jour un paramètre (les trois champs, l'URL reste unique)."""
    if db.get(SearchParameterModel, search_parameter_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Paramètre de recherche {search_parameter_id} introuvable",
        )
    existing = search_parameters_repository.get_by_url(db, body.url)
    if existing is not None and existing.id != search_parameter_id:
        raise HTTPException(
            status_code=409,
            detail=f"L'URL '{body.url}' est déjà utilisée par « {existing.title} »",
        )
    row = search_parameters_repository.update(
        db, search_parameter_id, body.model_dump()
    )
    # Émet l'UPDATE (persiste la ligne, `updated_at` rafraîchi via RETURNING)
    # AVANT de recharger : sans flush explicite, `db.refresh` relirait l'ancien
    # état et effacerait les modifications en attente (jamais persistées).
    db.flush()
    db.refresh(row)
    return SearchParameterOut.model_validate(row)


@router.put(
    "/search-parameters/{search_parameter_id}/activate",
    response_model=SearchParameterOut,
)
def activate_search_parameter(
    search_parameter_id: int, db: Session = Depends(get_db)
) -> SearchParameterOut:
    """Rend le paramètre actif (traité par l'agent de recherche)."""
    if not search_parameters_repository.set_active(db, search_parameter_id, True):
        raise HTTPException(
            status_code=404,
            detail=f"Paramètre de recherche {search_parameter_id} introuvable",
        )
    row = db.get(SearchParameterModel, search_parameter_id)
    return SearchParameterOut.model_validate(row)


@router.put(
    "/search-parameters/{search_parameter_id}/deactivate",
    response_model=SearchParameterOut,
)
def deactivate_search_parameter(
    search_parameter_id: int, db: Session = Depends(get_db)
) -> SearchParameterOut:
    """Désactive le paramètre (ignoré par l'agent de recherche)."""
    if not search_parameters_repository.set_active(db, search_parameter_id, False):
        raise HTTPException(
            status_code=404,
            detail=f"Paramètre de recherche {search_parameter_id} introuvable",
        )
    row = db.get(SearchParameterModel, search_parameter_id)
    return SearchParameterOut.model_validate(row)


@router.delete("/search-parameters/{search_parameter_id}", status_code=204)
def delete_search_parameter(
    search_parameter_id: int, db: Session = Depends(get_db)
) -> None:
    """Supprime un paramètre de recherche."""
    if not search_parameters_repository.delete(db, search_parameter_id):
        raise HTTPException(
            status_code=404,
            detail=f"Paramètre de recherche {search_parameter_id} introuvable",
        )
    return None
