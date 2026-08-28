"""Tests du service agent de recherche
(``src/services/search_parameters_agent.py``).

La base est mockée au niveau module : ``session_scope`` et
``search_parameters_repository`` (du module agent) sont remplacés par des fakes,
aucun PostgreSQL réel n'est contacté. L'ingestion est un fake
(``ingestor.run(url, max_offers)``) configurable pour renvoyer un
``URLIngestResult`` ou lever les exceptions du pipeline — le service doit
comptabiliser l'échec sans interrompre la boucle.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.core.scoring.url_offer_extractor import (
    LLMExtractionError,
    URLScrapingError,
)
from src.services import search_parameters_agent as agent_module
from src.services.search_parameters_agent import SearchParametersAgentService
from src.services.url_job_ingestor import (
    URLOfferDuplicateError,
    URLIngestResult,
)


@contextmanager
def _fake_scope(session):
    yield session


class _FakeRepo:
    """Repro du repository : ``list_all``/``get_by_id`` renvoient les paramètres
    configurés."""

    def __init__(self, parameters=()):
        self.parameters = list(parameters)

    def list_all(self, session):
        self.seen_session = session
        return self.parameters

    def get_by_id(self, session, param_id):
        self.seen_session = session
        for p in self.parameters:
            if p.id == param_id:
                return p
        return None


class _FakeIngestor:
    """Repro de l'ingestion par URL : enregistre les appels et lève ou
    renvoie selon l'URL demandée."""

    def __init__(self, results=None, errors=None):
        self.results = dict(results or {})  # url -> URLIngestResult
        self.errors = dict(errors or {})  # url -> exception à lever
        self.calls = []  # (url, max_offers) reçus

    def run(self, url, max_offers):
        self.calls.append((url, max_offers))
        if url in self.errors:
            raise self.errors[url]
        return self.results[url]


def _param(
    param_id, url, max_offers=5, title="Paramètre", source="hellowork", is_active=True
):
    return SimpleNamespace(
        id=param_id,
        title=f"{title} {param_id}",
        source=source,
        url=url,
        max_offers=max_offers,
        is_active=is_active,
    )


def _install(monkeypatch, repo, ingestor):
    """Branche le module agent sur un repository et une session fakes."""
    session = SimpleNamespace()
    monkeypatch.setattr(agent_module, "session_scope", lambda: _fake_scope(session))
    monkeypatch.setattr(agent_module, "search_parameters_repository", repo)
    return SearchParametersAgentService(ingestor=ingestor)


def _ok_result(added=1, already_present=0):
    return URLIngestResult(keys=[], added=added, already_present=already_present)


def test_run_ingests_all_parameters(monkeypatch):
    params = [
        _param(1, "https://example.com/search/1"),
        _param(2, "https://example.com/search/2"),
    ]
    ingestor = _FakeIngestor(
        results={
            "https://example.com/search/1": _ok_result(added=3, already_present=1),
            "https://example.com/search/2": _ok_result(added=2),
        }
    )
    service = _install(monkeypatch, _FakeRepo(params), ingestor)

    summary = service.run()

    assert summary["total"] == 2
    assert summary["succeeded"] == 2
    assert summary["added_offers"] == 5
    assert summary["already_present"] == 1
    assert ingestor.calls == [
        ("https://example.com/search/1", 5),
        ("https://example.com/search/2", 5),
    ]
    assert [p["status"] for p in summary["parameters"]] == ["ok", "ok"]


def test_run_passes_max_offers_from_parameter(monkeypatch):
    param = _param(1, "https://example.com/search/1", max_offers=12)
    ingestor = _FakeIngestor(results={"https://example.com/search/1": _ok_result()})
    service = _install(monkeypatch, _FakeRepo([param]), ingestor)

    service.run()

    assert ingestor.calls == [("https://example.com/search/1", 12)]


def test_run_duplicate_does_not_stop_loop(monkeypatch):
    params = [
        _param(1, "https://example.com/dup"),
        _param(2, "https://example.com/ok"),
    ]
    ingestor = _FakeIngestor(
        errors={"https://example.com/dup": URLOfferDuplicateError("déjà en base")},
        results={"https://example.com/ok": _ok_result()},
    )
    service = _install(monkeypatch, _FakeRepo(params), ingestor)

    summary = service.run()

    assert summary["duplicates"] == 1
    assert summary["succeeded"] == 1
    assert ingestor.calls == [
        ("https://example.com/dup", 5),
        ("https://example.com/ok", 5),
    ]
    assert [p["status"] for p in summary["parameters"]] == ["duplicate", "ok"]


def test_run_scraping_and_llm_failures_counted(monkeypatch):
    params = [
        _param(1, "https://example.com/scrape"),
        _param(2, "https://example.com/llm"),
    ]
    ingestor = _FakeIngestor(
        errors={
            "https://example.com/scrape": URLScrapingError("page sans offre"),
            "https://example.com/llm": LLMExtractionError("LLM indisponible"),
        }
    )
    service = _install(monkeypatch, _FakeRepo(params), ingestor)

    summary = service.run()

    assert summary["scraping_failed"] == 1
    assert summary["llm_failed"] == 1
    assert summary["succeeded"] == 0
    assert [p["status"] for p in summary["parameters"]] == [
        "scraping_failed",
        "llm_failed",
    ]


def test_run_generic_exception_does_not_stop_loop(monkeypatch):
    params = [
        _param(1, "https://example.com/crash"),
        _param(2, "https://example.com/ok"),
    ]
    ingestor = _FakeIngestor(
        errors={"https://example.com/crash": RuntimeError("boom")},
        results={"https://example.com/ok": _ok_result()},
    )
    service = _install(monkeypatch, _FakeRepo(params), ingestor)

    summary = service.run()

    assert summary["other_failed"] == 1
    assert summary["succeeded"] == 1
    assert ingestor.calls == [
        ("https://example.com/crash", 5),
        ("https://example.com/ok", 5),
    ]


def test_run_skips_inactive_parameters(monkeypatch):
    """Un paramètre désactivé n'est pas ingéré (ni compté dans le résumé)."""
    params = [
        _param(1, "https://example.com/active"),
        _param(2, "https://example.com/inactive", is_active=False),
    ]
    ingestor = _FakeIngestor(
        results={"https://example.com/active": _ok_result()}
    )
    service = _install(monkeypatch, _FakeRepo(params), ingestor)

    summary = service.run()

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert ingestor.calls == [("https://example.com/active", 5)]
    assert [p["status"] for p in summary["parameters"]] == ["ok"]


def test_run_empty_table(monkeypatch):
    ingestor = _FakeIngestor()
    service = _install(monkeypatch, _FakeRepo([]), ingestor)

    summary = service.run()

    assert summary == {
        "total": 0,
        "succeeded": 0,
        "duplicates": 0,
        "scraping_failed": 0,
        "llm_failed": 0,
        "other_failed": 0,
        "added_offers": 0,
        "already_present": 0,
        "parameters": [],
    }
    assert ingestor.calls == []


def test_run_parameter_by_id_ingests_one(monkeypatch):
    """Un lancement unitaire traite une seule recherche et cumule ses compteurs."""
    param = _param(1, "https://example.com/search/1")
    ingestor = _FakeIngestor(
        results={"https://example.com/search/1": _ok_result(added=3, already_present=1)}
    )
    service = _install(monkeypatch, _FakeRepo([param]), ingestor)

    summary = service.run_parameter_by_id(1)

    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert summary["added_offers"] == 3
    assert summary["already_present"] == 1
    assert ingestor.calls == [("https://example.com/search/1", 5)]
    # L'entrée expose titre / source / URL / max_offers (bannière d'un run
    # unitaire dans l'UI).
    entry = summary["parameters"][0]
    assert entry["status"] == "ok"
    assert entry["title"] == "Paramètre 1"
    assert entry["source"] == "hellowork"
    assert entry["url"] == "https://example.com/search/1"
    assert entry["max_offers"] == 5
    assert entry["added"] == 3
    assert entry["already_present"] == 1


def test_run_parameter_by_id_ignores_is_active(monkeypatch):
    """Un lancement unitaire traite une recherche inactive (test ponctuel,
    contrairement à ``run()`` qui filtre les inactifs)."""
    param = _param(1, "https://example.com/search/1", is_active=False)
    ingestor = _FakeIngestor(
        results={"https://example.com/search/1": _ok_result()}
    )
    service = _install(monkeypatch, _FakeRepo([param]), ingestor)

    summary = service.run_parameter_by_id(1)

    assert summary["succeeded"] == 1
    assert ingestor.calls == [("https://example.com/search/1", 5)]


def test_run_parameter_by_id_failure_counted(monkeypatch):
    """Un échec unitaire est compté dans le résumé (même forme que ``run()``)."""
    param = _param(1, "https://example.com/dup")
    ingestor = _FakeIngestor(
        errors={"https://example.com/dup": URLOfferDuplicateError("déjà en base")}
    )
    service = _install(monkeypatch, _FakeRepo([param]), ingestor)

    summary = service.run_parameter_by_id(1)

    assert summary["duplicates"] == 1
    assert summary["succeeded"] == 0
    assert summary["parameters"][0]["status"] == "duplicate"


def test_run_parameter_by_id_unknown_raises(monkeypatch):
    """Id inconnu → ValueError (converti en 404 par la route)."""
    ingestor = _FakeIngestor()
    service = _install(
        monkeypatch, _FakeRepo([_param(1, "https://example.com/a")]), ingestor
    )

    with pytest.raises(ValueError, match="introuvable"):
        service.run_parameter_by_id(999)

    assert ingestor.calls == []
