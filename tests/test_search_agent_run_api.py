"""Tests unitaires de l'endpoint d'exécution de l'agent de recherche.

``POST /api/v1/search-parameters/run`` délègue à
``SearchParametersAgentService().run()`` (même pipeline que le DAG
``search_parameters_agent``). Le service est remplacé par un fake — aucun
scraping, aucun LLM, aucune base. ``TestClient(app)`` sans contexte n'exécute
pas le lifespan (pas d'``ensure_schema`` sur la base de dev).
"""

from fastapi.testclient import TestClient

from api.app.main import app


# Résumé minimal du service (forme du XCom du DAG) : valeurs déterministes pour
# vérifier que la route transmet la réponse telle quelle.
_SAMPLE_SUMMARY = {
    "total": 2,
    "succeeded": 1,
    "duplicates": 0,
    "scraping_failed": 0,
    "llm_failed": 1,
    "other_failed": 0,
    "added_offers": 3,
    "already_present": 2,
    "parameters": [
        {
            "id": 1,
            "title": "Data Engineer",
            "url": "https://example.com/jobs",
            "max_offers": 5,
            "status": "ok",
            "added": 3,
            "already_present": 2,
        },
        {
            "id": 2,
            "title": "Data Analyst",
            "url": "https://example.com/analyst",
            "max_offers": 5,
            "status": "llm_failed",
        },
    ],
}


class _FakeAgentService:
    """Fake compatible avec le constructeur (ingestor optionnel) et ``run``."""

    def __init__(self, ingestor=None):
        self.ingestor = ingestor

    def run(self):
        return _SAMPLE_SUMMARY


def _install_fake(monkeypatch, service_cls):
    """Remplace le service dans le module du routeur (patch par attribution)."""
    monkeypatch.setattr(
        "api.app.routers.search_parameters.SearchParametersAgentService",
        service_cls,
    )


def test_run_search_agent_returns_summary(monkeypatch):
    _install_fake(monkeypatch, _FakeAgentService)
    client = TestClient(app)

    r = client.post("/api/v1/search-parameters/run")

    assert r.status_code == 200
    body = r.json()
    assert body == _SAMPLE_SUMMARY
    assert body["added_offers"] == 3
    assert body["already_present"] == 2
    assert body["llm_failed"] == 1
    assert len(body["parameters"]) == 2


def test_run_search_agent_error_becomes_500(monkeypatch):
    class _BoomService:
        def __init__(self, ingestor=None):
            self.ingestor = ingestor

        def run(self):
            raise RuntimeError("Scraping indisponible")

    _install_fake(monkeypatch, _BoomService)
    # raise_server_exceptions=False : l'exception du fake devient une réponse
    # 500 plutôt que de remonter jusqu'au test.
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/api/v1/search-parameters/run")

    assert r.status_code == 500
