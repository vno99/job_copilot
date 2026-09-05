"""Tests du service d'ingestion d'offres depuis une URL
(``src/services/url_job_ingestor.py``).

La base est mockée au niveau module : ``session_scope`` et
``job_offer_repository`` (du module ``url_job_ingestor``) sont remplacés par des
fakes, aucun PostgreSQL réel n'est contacté. Le scraper est un fake (``fetch_text``
par URL) ; l'extraction LLM est servie par le fixture autouse ``_mock_llm`` du
conftest (branche ``=== OFFRE DEPUIS URL ===``, offre unique) ou surchargée par
une **file de réponses** pour les chemins liste (classification de la page, puis
une réponse par offre récupérée individuellement).
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from src.core.scoring import score_engine
from src.core.scoring.url_offer_extractor import (
    LIST_MAX_URLS,
    MAX_PAGE_CHARS,
    LLMExtractionError,
    URLScrapingError,
)
from src.services import url_job_ingestor as ingestor_module
from src.services.url_job_ingestor import (
    URLJobIngestorService,
    URLOfferDuplicateError,
)

TEST_URL = "https://example.com/from-url-test/1"
URL_HASH = hashlib.sha256(TEST_URL.encode("utf-8")).hexdigest()


@contextmanager
def _fake_scope(session):
    yield session


class _FakeRepo:
    """Repro du repository : ``get_by_url`` / ``get_by_url_for_update`` (offre
    unique), ``existing_urls`` (liste, par colonne ``url``) et ``upsert_many``
    (compteurs configurables).

    ``upsert_call_count`` permet aux tests de vérifier que l'ingestor a bien
    effectué un seul appel batché (``upsert_many([row1, row2, …])``) plutôt
    qu'un appel par offre.
    """

    def __init__(self, existing_url=None, present_urls=(), upsert_result=None):
        self.existing_url = existing_url  # offre renvoyée par get_by_url (ou None)
        self.present_urls = set(present_urls)  # URLs déjà en base (existing_urls)
        # Si ``upsert_result`` est ``None`` : retourne dynamiquement
        # ``(len(rows), 0, 0)`` (mode batch, où le repo retourne le nombre
        # de rows ingérées). Sinon, force une valeur fixe (utile pour tester
        # le cas TOCTOU où ``ingested == 0``).
        self.upsert_result = upsert_result
        self.upsert_call_count = 0
        self.upsert_calls: List[List[Dict]] = []
        self.seen_urls = []  # appels à get_by_url (chemin offre unique)
        self.seen_urls_for_update = []  # appels à get_by_url_for_update
        self.rows = []

    def get_by_url(self, _session, url):
        self.seen_urls.append(url)
        return self.existing_url

    def get_by_url_for_update(self, _session, url):
        # Variante verrouillée : même comportement que ``get_by_url`` côté fake.
        # Trace les appels pour que les tests puissent vérifier que le verrou
        # est bien pris avant l'upsert.
        self.seen_urls_for_update.append(url)
        return self.existing_url

    def existing_urls(self, _session, urls):
        return {u for u in urls if u in self.present_urls}

    def upsert_many(self, _session, rows):
        self.upsert_call_count += 1
        self.upsert_calls.append(list(rows))
        self.rows.extend(rows)
        if self.upsert_result is not None:
            return self.upsert_result
        # Mode batch : retourne ``(len(rows), 0, 0)`` par défaut — toutes les
        # rows sont ingérées.
        return (len(rows), 0, 0)


class _FakeScraper:
    """Retourne un texte par URL ; lève ``errors[url]`` s'il est présent."""

    def __init__(self, texts=None, errors=None):
        self.texts = dict(texts or {})
        self.errors = dict(errors or {})
        self.called_urls = []

    def fetch_text(self, url):
        self.called_urls.append(url)
        if url in self.errors:
            raise self.errors[url]
        if url in self.texts:
            return self.texts[url]
        return "<html><body>offre par défaut</body></html>"


def _install(monkeypatch, repo):
    """Branche ``url_job_ingestor`` sur une session et un repository fakes."""
    session = SimpleNamespace()
    monkeypatch.setattr(ingestor_module, "session_scope", lambda: _fake_scope(session))
    monkeypatch.setattr(ingestor_module, "job_offer_repository", repo)
    return session


def _mock_url_llm(monkeypatch, payloads, capture=None):
    """Remplace ``URL_SCRAPER_LLM`` par des réponses JSON déterministes
    consommées dans l'ordre : la classification de la page, puis une réponse par
    offre récupérée individuellement (fetch + extraction mono-offre).

    ``capture`` : liste optionnelle recevant les ``messages`` de chaque
    ``invoke`` (pour asserter sur le prompt construit, ex. ``max_urls``)."""

    queue = list(payloads)

    def invoke(_messages):
        if not queue:
            raise AssertionError("URL_SCRAPER_LLM invoqué plus que prévu")
        if capture is not None:
            capture.append(_messages)
        return SimpleNamespace(content=json.dumps(queue.pop(0), ensure_ascii=False))

    monkeypatch.setattr(
        score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=invoke)
    )


def _single_payload(title="Data Engineer H/F", **overrides):
    """Réponse « offre unique » du LLM (contenu complet)."""
    payload = {
        "title": title,
        "company": "Acme",
        "location": "Paris - 75",
        "contract_type": "CDI",
        "description": f"Description de {title}",
        "published_date": "2026-05-22",
        "experience": "3 ans",
        "diploma": "Bac +5",
    }
    payload.update(overrides)
    return {"page_type": "single", "offer": payload}


def _list_payload(*urls):
    """Réponse « liste d'offres » du LLM : uniquement les URLs."""
    return {"page_type": "list", "offers": [{"url": u} for u in urls]}


def _sha(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Chemin « offre unique » : dédoublonnage 409
# ---------------------------------------------------------------------------


def test_run_raises_on_duplicate(monkeypatch):
    """Page d'offre unique déjà en base : 409, après fetch + classification LLM
    (on ne sait distinguer offre unique/liste qu'après le LLM)."""
    repo = _FakeRepo(existing_url=SimpleNamespace(id=7))
    _install(monkeypatch, repo)
    scraper = _FakeScraper()

    with pytest.raises(URLOfferDuplicateError):
        URLJobIngestorService(scraper=scraper).run(TEST_URL)

    assert scraper.called_urls == [TEST_URL]
    assert repo.seen_urls_for_update == [TEST_URL]
    assert repo.rows == []


def test_run_raises_on_toctou(monkeypatch):
    """Une insertion concurrente (ingested == 0) en offre unique est un doublon."""
    repo = _FakeRepo(existing_url=None, upsert_result=(0, 0, 0))
    _install(monkeypatch, repo)

    with pytest.raises(URLOfferDuplicateError):
        URLJobIngestorService(scraper=_FakeScraper()).run(TEST_URL)

    assert repo.rows[0]["url"] == TEST_URL


# ---------------------------------------------------------------------------
# Chemin « offre unique » : flux complet
# ---------------------------------------------------------------------------


def test_run_full_flow(monkeypatch):
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    scraper = _FakeScraper()
    service = URLJobIngestorService(scraper=scraper)

    result = service.run(TEST_URL)

    assert result.added == 1
    assert result.already_present == 0
    assert result.keys == [("example.com", URL_HASH)]
    # Contrôle de doublon de l'offre unique (verrou ``FOR UPDATE``) ;
    # pas de ``get_by_url`` non-verrouillé, plus de ``get_by_url`` en liste.
    assert repo.seen_urls_for_update == [TEST_URL]
    assert scraper.called_urls == [TEST_URL]

    # La ligne est celle du pipeline d'ingestion existant (normalize_job_offer).
    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["source"] == "example.com"
    assert row["source_job_id"] == URL_HASH
    assert row["url"] == TEST_URL
    assert row["title"] == "Data Engineer H/F"
    assert row["company"] == "Acme"
    assert row["location"] == "Paris - 75"
    assert row["contract_type"] == "CDI"
    assert row["description"] == "Python SQL Databricks"
    assert row["published_date"] == date(2026, 5, 22)
    assert row["experience"] == "3 ans"
    assert row["diploma"] == "Bac +5"
    # Les compétences sont extraites de la description par le pipeline existant.
    assert row["skills_extracted"]["hard_skills"]


def test_run_normalizes_url_before_dedup(monkeypatch):
    """Le fragment est retiré AVANT le contrôle de doublon et le fetch."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    scraper = _FakeScraper()

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL + "#section")

    normalized = TEST_URL
    assert repo.seen_urls_for_update == [normalized]
    assert scraper.called_urls == [normalized]
    assert repo.rows[0]["url"] == normalized
    assert result.keys == [("example.com", URL_HASH)]


# ---------------------------------------------------------------------------
# Chemin « contenu collé » : run_from_source (aucun fetch)
# ---------------------------------------------------------------------------


def _capture_extract(monkeypatch, captured):
    """Remplace ``extract_offer`` par une fonction qui capture le texte reçu puis
    renvoie une offre unique minimale (pour asserter sur la conversion du
    source avant l'extraction LLM)."""

    def fake_extract(text):
        captured.append(text)
        return {"title": "Offre", "company": "Acme", "description": "Python"}

    monkeypatch.setattr(ingestor_module, "extract_offer", fake_extract)
    return fake_extract


def test_run_from_source_ingests_single_offer(monkeypatch):
    """Le contenu collé remplace le fetch Playwright : aucune URL n'est
    récupérée, l'offre unique extraite par le LLM est ingérée via le chemin
    standard (source = domaine de l'URL soumise, clé = sha256 de l'URL)."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    scraper = _FakeScraper()

    result = URLJobIngestorService(scraper=scraper).run_from_source(
        TEST_URL, "Data Engineer - description de l'offre"
    )

    assert result.added == 1
    assert result.already_present == 0
    assert result.keys == [("example.com", URL_HASH)]
    # Aucun fetch : le contenu vient du champ texte collé.
    assert scraper.called_urls == []
    assert repo.seen_urls_for_update == [TEST_URL]
    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["source"] == "example.com"
    assert row["source_job_id"] == URL_HASH
    assert row["url"] == TEST_URL
    assert row["title"] == "Data Engineer H/F"
    assert row["company"] == "Acme"
    assert row["description"] == "Python SQL Databricks"
    # Les compétences sont extraites de la description par le pipeline existant.
    assert row["skills_extracted"]["hard_skills"]


def test_run_from_source_normalizes_url_before_dedup(monkeypatch):
    """Le fragment est retiré AVANT le contrôle de doublon et l'upsert."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)

    result = URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
        TEST_URL + "#section", "contenu"
    )

    assert repo.seen_urls_for_update == [TEST_URL]
    assert repo.rows[0]["url"] == TEST_URL
    assert result.keys == [("example.com", URL_HASH)]


def test_run_from_source_raises_on_duplicate(monkeypatch):
    """Une URL déjà en base → 409 (URLOfferDuplicateError), rien n'est upserté."""
    repo = _FakeRepo(existing_url=SimpleNamespace(id=7))
    _install(monkeypatch, repo)

    with pytest.raises(URLOfferDuplicateError):
        URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
            TEST_URL, "contenu"
        )
    assert repo.rows == []


def test_run_from_source_converts_html_source(monkeypatch):
    """Le source en HTML (code source de navigateur) est converti en texte
    structuré (balises retirées, blocs préservés) avant l'extraction : le LLM
    voit la mise en page, comme pour un fetch Playwright."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    captured: list[str] = []
    _capture_extract(monkeypatch, captured)

    URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
        TEST_URL,
        "<html><body><p>Missions</p><ul><li>Python</li><li>SQL</li></ul></body></html>",
    )

    text = captured[0]
    assert "<html" not in text
    assert "<li>" not in text
    assert "Missions" in text
    assert "Python" in text
    assert "SQL" in text


def test_run_from_source_passes_text_through(monkeypatch):
    """Un texte déjà brut est transmis tel quel à l'extraction (pas de balisage,
    pas de conversion)."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    captured: list[str] = []
    _capture_extract(monkeypatch, captured)
    source_text = "Data Engineer\n- Python\n- SQL"

    URLJobIngestorService(scraper=_FakeScraper()).run_from_source(TEST_URL, source_text)

    assert captured[0] == source_text


def test_run_from_source_bounds_text_to_max_page_chars(monkeypatch):
    """Un texte collé très long est borné à ``MAX_PAGE_CHARS`` avant l'envoi au
    LLM (budget de tokens, même borne que le chemin URL)."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    captured: list[str] = []
    _capture_extract(monkeypatch, captured)

    URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
        TEST_URL, "x" * (MAX_PAGE_CHARS * 2)
    )

    assert len(captured[0]) == MAX_PAGE_CHARS


def test_run_from_source_raises_when_not_a_single_offer(monkeypatch):
    """Le source d'une page de recherche (liste) collé → 422 (URLScrapingError) :
    le contenu collé est mono-offre, contrairement au fetch Playwright (liste)."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)
    _mock_url_llm(monkeypatch, [{"page_type": "none", "reason": "liste d'offres"}])

    with pytest.raises(URLScrapingError):
        URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
            TEST_URL, "Deux offres chez Acme"
        )
    assert repo.seen_urls == []
    assert repo.rows == []


def test_run_from_source_raises_on_invalid_url(monkeypatch):
    """Une URL invalide → 422 (URLScrapingError), sans appeler le LLM ni la base."""
    repo = _FakeRepo(existing_url=None)
    _install(monkeypatch, repo)

    with pytest.raises(URLScrapingError):
        URLJobIngestorService(scraper=_FakeScraper()).run_from_source(
            "pas une url", "contenu"
        )
    assert repo.seen_urls == []
    assert repo.rows == []


# ---------------------------------------------------------------------------
# Chemin « liste d'offres » : récupération individuelle des URLs nouvelles
# ---------------------------------------------------------------------------


def test_run_ingests_list_with_individual_urls(monkeypatch):
    """Une liste : chaque URL nouvelle est récupérée individuellement (fetch +
    extraction mono-offre) ; ``source_job_id`` = hash de l'URL de l'offre.

    Avec l'optimisation batch (1 seul ``upsert_many`` avec toutes les rows),
    le mock retourne ``(len(rows), 0, 0)`` = ``(2, 0, 0)``."""
    repo = _FakeRepo(present_urls=())
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o1": "offre Data Engineer",
            "https://example.com/o2": "offre Data Analyst",
        }
    )
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload("https://example.com/o1", "https://example.com/o2"),
            _single_payload("Data Engineer"),
            _single_payload("Data Analyst"),
        ],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 2
    assert result.already_present == 0
    assert result.keys == [
        ("example.com", _sha("https://example.com/o1")),
        ("example.com", _sha("https://example.com/o2")),
    ]
    # La page liste, puis chaque offre individuelle ; pas de get_by_url en liste.
    assert scraper.called_urls == [
        TEST_URL,
        "https://example.com/o1",
        "https://example.com/o2",
    ]
    assert repo.seen_urls == []
    assert [row["url"] for row in repo.rows] == [
        "https://example.com/o1",
        "https://example.com/o2",
    ]
    assert [row["source_job_id"] for row in repo.rows] == [
        _sha("https://example.com/o1"),
        _sha("https://example.com/o2"),
    ]


def test_run_list_skips_urls_already_in_db(monkeypatch):
    """Une URL déjà en base (par colonne ``url``) est sautée sans fetch ni
    extraction ; elle est comptée dans ``already_present``."""
    repo = _FakeRepo(present_urls={"https://example.com/o1"}, upsert_result=(1, 0, 0))
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o2": "offre Data Analyst",
        }
    )
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload("https://example.com/o1", "https://example.com/o2"),
            _single_payload("Data Analyst"),
        ],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 1
    assert result.already_present == 1
    assert result.keys == [("example.com", _sha("https://example.com/o2"))]
    # o1 (déjà en base) n'est jamais fetché.
    assert scraper.called_urls == [TEST_URL, "https://example.com/o2"]
    assert [row["url"] for row in repo.rows] == ["https://example.com/o2"]


def test_run_list_all_present_added_zero_is_not_an_error(monkeypatch):
    """Une liste dont toutes les URLs sont déjà en base : ``added==0``,
    ``already_present`` = le compte, PAS de 409 (chemin liste)."""
    repo = _FakeRepo(present_urls={"https://example.com/o1", "https://example.com/o2"})
    _install(monkeypatch, repo)
    scraper = _FakeScraper(texts={TEST_URL: "liste d'offres"})
    _mock_url_llm(
        monkeypatch,
        [_list_payload("https://example.com/o1", "https://example.com/o2")],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 0
    assert result.already_present == 2
    assert result.keys == []
    # Aucune offre n'est récupérée individuellement.
    assert scraper.called_urls == [TEST_URL]
    assert repo.rows == []


def test_run_list_max_offers_bounds_new_urls(monkeypatch):
    """``max_offers`` borne le nombre d'offres **nouvelles** récupérées (les
    premières dans l'ordre de la page), pas le nombre extrait de la liste."""
    repo = _FakeRepo(present_urls=())
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o1": "offre 1",
            "https://example.com/o2": "offre 2",
        }
    )
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload(
                "https://example.com/o1",
                "https://example.com/o2",
                "https://example.com/o3",
            ),
            _single_payload("Offre 1"),
            _single_payload("Offre 2"),
        ],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=2)

    assert result.added == 2
    assert result.already_present == 0
    # o3 est au-delà de max_offers : ni fetché ni extrait.
    assert scraper.called_urls == [TEST_URL, "https://example.com/o1", "https://example.com/o2"]
    assert [row["url"] for row in repo.rows] == ["https://example.com/o1", "https://example.com/o2"]


def test_run_list_dedups_duplicate_urls(monkeypatch):
    """Une même URL renvoyée plusieurs fois par le LLM (liste bruitée) n'est ni
    fetchée ni comptée deux fois : dédoublonnage en amont, ordre préservé. Sans
    lui, o1 serait fetché 2× (gaspillant un slot de ``max_offers``) et
    ``already_present`` serait gonflé à 2."""
    repo = _FakeRepo(present_urls={"https://example.com/o1"}, upsert_result=(1, 0, 0))
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o2": "offre Data Analyst",
        }
    )
    # o1 apparaît deux fois dans la liste ET est déjà en base ; seule o2 est à
    # récupérer. Une seule réponse mono-offre est servie : si le dédoublonnage
    # manquait, la boucle tenterait d'en consommer une seconde → le mock lève.
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload(
                "https://example.com/o1",
                "https://example.com/o1",
                "https://example.com/o2",
            ),
            _single_payload("Data Analyst"),
        ],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 1
    assert result.already_present == 1  # o1 compté une seule fois, pas le doublon
    assert result.keys == [("example.com", _sha("https://example.com/o2"))]
    # o1 (déjà en base) n'est jamais fetché ; o2 exactement une fois.
    assert scraper.called_urls == [TEST_URL, "https://example.com/o2"]
    assert [row["url"] for row in repo.rows] == ["https://example.com/o2"]


def test_run_list_skips_failed_individual_fetch(monkeypatch):
    """Un échec de récupération individuelle (URL indisponible, refusée par la
    barrière SSRF…) est ignoré : les autres offres sont ingérées et ``added``
    peut être < ``max_offers``."""
    repo = _FakeRepo(present_urls=(), upsert_result=(1, 0, 0))
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o2": "offre Data Analyst",
        },
        errors={
            "https://example.com/o1": URLScrapingError("l'offre n'est plus disponible"),
        },
    )
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload("https://example.com/o1", "https://example.com/o2"),
            _single_payload("Data Analyst"),
        ],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 1
    assert result.keys == [("example.com", _sha("https://example.com/o2"))]
    assert scraper.called_urls == [TEST_URL, "https://example.com/o1", "https://example.com/o2"]
    assert [row["url"] for row in repo.rows] == ["https://example.com/o2"]


def test_run_list_single_item_with_url_no_duplicate(monkeypatch):
    """Une liste à un seul item porte une URL individuelle : pas de 409 sur
    l'URL de la page, même si l'item est déjà en base (chemin liste)."""
    repo = _FakeRepo(present_urls={"https://example.com/o1"})
    _install(monkeypatch, repo)
    scraper = _FakeScraper(texts={TEST_URL: "liste d'une offre"})
    _mock_url_llm(
        monkeypatch,
        [_list_payload("https://example.com/o1")],
    )

    result = URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    assert result.added == 0
    assert result.already_present == 1
    assert result.keys == []
    assert repo.seen_urls == []  # pas de pré-contrôle get_by_url en liste


def test_run_requests_urls_bounded_to_need(monkeypatch):
    """La classification demande au LLM une marge d'URLs proportionnée à
    ``max_offers`` (2 ×, plancher 10), pas ``LIST_MAX_URLS`` — pour qu'une
    liste aux URLs longues (ex. Indeed, ``pagead/clk``) reste sous le budget de
    tokens d'extraction."""
    repo = _FakeRepo(present_urls=())
    _install(monkeypatch, repo)
    scraper = _FakeScraper(
        texts={
            TEST_URL: "liste d'offres",
            "https://example.com/o1": "offre Data Engineer",
        }
    )
    captured = []
    _mock_url_llm(
        monkeypatch,
        [
            _list_payload("https://example.com/o1"),
            _single_payload("Data Engineer"),
        ],
        capture=captured,
    )

    URLJobIngestorService(scraper=scraper).run(TEST_URL, max_offers=5)

    prompt = captured[0][1].content
    assert "au plus 10" in prompt  # 2 × max_offers, plancher 10


def test_urls_to_request_scales_with_max_offers():
    """``_urls_to_request`` borne la demande : plancher, échelle sur
    ``max_offers`` et plafond à ``LIST_MAX_URLS``."""
    service = URLJobIngestorService(scraper=_FakeScraper())
    assert service._urls_to_request(1) == 10  # plancher
    assert service._urls_to_request(5) == 10
    assert service._urls_to_request(12) == 24
    assert service._urls_to_request(20) == 40
    assert service._urls_to_request(99) == LIST_MAX_URLS  # plafond


# ---------------------------------------------------------------------------
# Erreurs propagées
# ---------------------------------------------------------------------------


def test_run_raises_on_invalid_url(monkeypatch):
    _install(monkeypatch, _FakeRepo())

    service = URLJobIngestorService(scraper=_FakeScraper())
    with pytest.raises(URLScrapingError):
        service.run("pas une url")
    with pytest.raises(URLScrapingError):
        service.run("file:///etc/passwd")


def test_run_raises_when_fetch_fails(monkeypatch):
    repo = _FakeRepo()
    _install(monkeypatch, repo)
    scraper = _FakeScraper(errors={TEST_URL: URLScrapingError("Récupération impossible")})

    with pytest.raises(URLScrapingError):
        URLJobIngestorService(scraper=scraper).run(TEST_URL)

    assert repo.rows == []


def test_run_raises_when_page_not_offer(monkeypatch):
    repo = _FakeRepo()
    _install(monkeypatch, repo)
    # Le LLM renvoie une page non-offre : pas d'offre exploitable → 422.
    _mock_url_llm(
        monkeypatch, [{"page_type": "none", "reason": "page d'accueil"}]
    )

    with pytest.raises(URLScrapingError):
        URLJobIngestorService(scraper=_FakeScraper()).run(TEST_URL)

    assert repo.rows == []


def test_run_raises_when_llm_unavailable(monkeypatch):
    repo = _FakeRepo()
    _install(monkeypatch, repo)
    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", None)

    with pytest.raises(LLMExtractionError):
        URLJobIngestorService(scraper=_FakeScraper()).run(TEST_URL)

    assert repo.rows == []
