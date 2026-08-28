"""Tests d'intégration des paramètres de recherche (nécessitent postgres-data).

CRUD de la table ``search_parameters`` : liste, création (URL unique, trim,
validation http/https), mise à jour et suppression. Aucun LLM impliqué.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app
from src.infrastructure.db.session import get_engine

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_postgres")]


def _db_up() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture()
def cleanup():
    yield
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM search_parameters WHERE url LIKE "
                "'https://example.com/api-test/%'"
            )
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _payload(**overrides):
    payload = {
        "title": "Data Engineer",
        "source": "hellowork",
        "url": "https://example.com/api-test/1",
    }
    payload.update(overrides)
    return payload


def test_create_and_list(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # POST 201 : valeurs trimées, timestamps exposés
    r = client.post(
        "/api/v1/search-parameters",
        json=_payload(
            title="  Data Engineer  ", source="  hellowork  ", url=" https://example.com/api-test/1 "
        ),
    )
    assert r.status_code == 201
    p = r.json()
    assert p["title"] == "Data Engineer"
    assert p["source"] == "hellowork"
    assert p["url"] == "https://example.com/api-test/1"
    assert p["max_offers"] == 5  # défaut serveur (slider 1 → 20)
    assert p["is_active"] is True  # un paramètre est actif à la création
    assert p["created_at"] is not None
    assert p["updated_at"] is not None

    # Second POST : la liste est triée du plus récent au plus ancien
    assert (
        client.post(
            "/api/v1/search-parameters",
            json=_payload(url="https://example.com/api-test/2", title="Data Analyst"),
        ).status_code
        == 201
    )
    listing = client.get("/api/v1/search-parameters").json()
    assert [x["url"] for x in listing] == [
        "https://example.com/api-test/2",
        "https://example.com/api-test/1",
    ]
    assert [x["title"] for x in listing] == ["Data Analyst", "Data Engineer"]


def test_create_duplicate_url_conflict(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    assert (
        client.post(
            "/api/v1/search-parameters", json=_payload()
        ).status_code
        == 201
    )
    # Même URL → 409 (détail portant le titre du paramètre existant).
    r = client.post(
        "/api/v1/search-parameters",
        json=_payload(title="Doublon"),
    )
    assert r.status_code == 409
    assert "Data Engineer" in r.json()["detail"]


def test_create_and_patch_max_offers(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # POST avec max_offers=20 → 201, la valeur est persistée et exposée.
    p = client.post(
        "/api/v1/search-parameters",
        json=_payload(max_offers=20),
    ).json()
    assert p["max_offers"] == 20

    # PATCH max_offers=7 → 200, la valeur est remplacée (PATCH complet).
    r = client.patch(
        f"/api/v1/search-parameters/{p['id']}",
        json=_payload(max_offers=7),
    )
    assert r.status_code == 200
    assert r.json()["max_offers"] == 7


def test_patch(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p1 = client.post("/api/v1/search-parameters", json=_payload()).json()
    p2 = client.post(
        "/api/v1/search-parameters",
        json=_payload(url="https://example.com/api-test/2", title="Data Analyst"),
    ).json()

    # PATCH 200 : les trois champs sont remplacés (PATCH complet)
    r = client.patch(
        f"/api/v1/search-parameters/{p1['id']}",
        json=_payload(
            title="Data Engineer Senior",
            source="linkedin",
            url="https://example.com/api-test/1b",
        ),
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["id"] == p1["id"]
    assert updated["title"] == "Data Engineer Senior"
    assert updated["source"] == "linkedin"
    assert updated["url"] == "https://example.com/api-test/1b"
    assert updated["updated_at"] is not None

    # 409 : l'URL cible est déjà utilisée par un AUTRE paramètre
    r = client.patch(
        f"/api/v1/search-parameters/{p1['id']}",
        json=_payload(url=p2["url"], title="Conflicteur"),
    )
    assert r.status_code == 409

    # 404 : paramètre inexistant
    assert (
        client.patch(
            "/api/v1/search-parameters/999999", json=_payload()
        ).status_code
        == 404
    )


def test_create_validation(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # URL non-http(s) → 422
    for bad_url in ("pas une url", "file:///etc/passwd", "ftp://example.com/x"):
        assert (
            client.post(
                "/api/v1/search-parameters", json=_payload(url=bad_url)
            ).status_code
            == 422
        )

    # Champ vide après trim → 422 (titre, source, URL)
    for field in ("title", "source", "url"):
        assert (
            client.post(
                "/api/v1/search-parameters", json=_payload(**{field: "   "})
            ).status_code
            == 422
        )

    # Source trop longue (>100) → 422
    assert (
        client.post(
            "/api/v1/search-parameters", json=_payload(source="x" * 101)
        ).status_code
        == 422
    )

    # max_offers hors bornes (0, 21) → 422 (POST et PATCH)
    for bad in (0, 21):
        assert (
            client.post(
                "/api/v1/search-parameters", json=_payload(max_offers=bad)
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/api/v1/search-parameters/999999", json=_payload(max_offers=bad)
            ).status_code
            == 422
        )


def test_activate_deactivate(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p = client.post("/api/v1/search-parameters", json=_payload()).json()
    assert p["is_active"] is True

    # Désactivation : is_active false — le paramètre est ignoré par l'agent.
    r = client.put(f"/api/v1/search-parameters/{p['id']}/deactivate")
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # Réactivation : is_active true.
    r = client.put(f"/api/v1/search-parameters/{p['id']}/activate")
    assert r.status_code == 200
    assert r.json()["is_active"] is True

    # Paramètre inconnu → 404 (activate et deactivate).
    assert (
        client.put("/api/v1/search-parameters/999999/activate").status_code
        == 404
    )
    assert (
        client.put("/api/v1/search-parameters/999999/deactivate").status_code
        == 404
    )


def test_delete(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p = client.post(
        "/api/v1/search-parameters", json=_payload()
    ).json()

    # DELETE 204 : la liste ne contient plus le paramètre
    assert client.delete(f"/api/v1/search-parameters/{p['id']}").status_code == 204
    assert [
        x["id"] for x in client.get("/api/v1/search-parameters").json()
    ] == []

    # Second DELETE → 404
    assert client.delete(f"/api/v1/search-parameters/{p['id']}").status_code == 404


def test_run_parameter_not_found(client):
    """POST /search-parameters/{id}/run sur un id inconnu → 404, sans réseau
    (get_by_id → None → ValueError converti par la route)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    assert (
        client.post("/api/v1/search-parameters/999999/run").status_code == 404
    )


def test_run_parameter_unit(monkeypatch, client, cleanup):
    """POST /search-parameters/{id}/run → 200, résumé d'ingestion d'une seule
    recherche. Le service est mocké (aucun réseau/LLM) : seul le mapping
    route → service est exercé — le comportement du service est couvert
    unitairement (tests/test_search_parameters_agent.py)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p = client.post("/api/v1/search-parameters", json=_payload()).json()

    summary = {
        "total": 1,
        "succeeded": 1,
        "duplicates": 0,
        "scraping_failed": 0,
        "llm_failed": 0,
        "other_failed": 0,
        "added_offers": 3,
        "already_present": 1,
        "parameters": [
            {
                "id": p["id"],
                "title": p["title"],
                "source": p["source"],
                "url": p["url"],
                "max_offers": p["max_offers"],
                "status": "ok",
                "added": 3,
                "already_present": 1,
            }
        ],
    }

    class _FakeService:
        def run_parameter_by_id(self, param_id):
            assert param_id == p["id"]
            return summary

    monkeypatch.setattr(
        "api.app.routers.search_parameters.SearchParametersAgentService",
        lambda: _FakeService(),
    )

    r = client.post(f"/api/v1/search-parameters/{p['id']}/run")
    assert r.status_code == 200
    assert r.json() == summary
