"""Tests d'intégration de l'API FastAPI (nécessitent postgres-data démarré)."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app
from src.core.domain.candidate_profile import CandidateProfile
from src.core.scoring import score_engine
from src.infrastructure.db.repositories import (
    candidate_profile_repository,
    job_offer_repository,
    match_result_repository,
)
from src.infrastructure.db.session import get_engine, session_scope
from src.interfaces.scrapers.url.scraper import URLScraper
from src.services.url_job_ingestor import SOURCE_MAX_CHARS

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_postgres")]

# CV suffisamment riche pour que le matching dépasse le seuil de génération
# (scoring.yaml match_threshold = 60).
RICH_CV = (
    "# Data Engineer\n"
    "## Résumé\n"
    "Data Engineer expérimenté, construction de pipelines data.\n"
    "## Compétences\n"
    "- Python\n"
    "- SQL\n"
    "- Airflow\n"
    "## Expérience\n"
    "### Data Engineer — Acme (2020 - 2024)\n"
    "- Pipelines d'ingestion\n"
    "## Formation\n"
    "- Master\n"
)


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
                """
                DELETE FROM cv_version
                  WHERE job_offer_id IN
                    (SELECT id FROM job_offer WHERE source_job_id LIKE 'api-test-%');
                DELETE FROM letter_version
                  WHERE job_offer_id IN
                    (SELECT id FROM job_offer WHERE source_job_id LIKE 'api-test-%');
                DELETE FROM match_result
                  WHERE job_offer_id IN
                    (SELECT id FROM job_offer WHERE source_job_id LIKE 'api-test-%');
                DELETE FROM job_offer WHERE source_job_id LIKE 'api-test-%';
                DELETE FROM job_offer WHERE url LIKE 'https://example.com/from-url-test/%';
                DELETE FROM job_offer WHERE url LIKE 'https://example.com/from-source-test/%';
                DELETE FROM candidate_profile WHERE profile_name LIKE 'api_test%';
                """
            )
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _insert_offer(
    source_job_id: str,
    title: str,
    skills,
    *,
    company: str = "Acme",
    location: str = "Paris",
    source: str = "hellowork",
    ingested_at=None,
) -> int:
    offer = {
        "source": source,
        "source_job_id": source_job_id,
        "url": f"https://example.com/{source_job_id}",
        "title": title,
        "company": company,
        "location": location,
        "contract_type": "CDI",
        "experience": "3 ans",
        "diploma": "Master",
        "description": " ".join(skills),
        "skills_extracted": {
            "hard_skills": [
                {"name": n, "category": "langage", "level": "maîtrise", "mandatory": True}
                for n in skills
            ],
            "soft_skills": [],
            "certifications": [],
        },
        "raw_payload": {"source": "test"},
        "content_hash": f"hash-{source_job_id}",
    }
    if ingested_at is not None:
        offer["ingested_at"] = ingested_at
    with session_scope() as session:
        job_offer_repository.upsert_many(session, [offer])
        row = session.execute(
            text("SELECT id FROM job_offer WHERE source_job_id = :sid"),
            {"sid": source_job_id},
        ).scalar()
    return row


def _set_archived(offer_id: int, archived: bool = True) -> None:
    """Marque directement une offre comme archivée (ou active) en base."""
    with session_scope() as session:
        job_offer_repository.set_archived(session, offer_id, archived)


def _upload(client, filename: str, content: str, profile_name: str):
    return client.post(
        "/api/v1/profiles",
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        data={"profile_name": profile_name},
    )


def test_health(client):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ok"}


def test_profile_upload_and_activation(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # Premier upload : aucun profil actif -> devient actif
    r1 = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n- SQL\n", "api_test_prof"
    )
    assert r1.status_code == 201
    p1 = r1.json()
    assert p1["is_active"] is True
    assert "Python" in p1["skills"]

    # Second upload : un profil actif existe -> reste inactif
    p2 = _upload(
        client, "cv2.md", "# Paul\n## Compétences\n- Java\n", "api_test_prof2"
    ).json()
    assert p2["is_active"] is False

    # Activation manuelle de p2 : p1 devient inactif (un seul actif garanti)
    assert client.put(f"/api/v1/profiles/{p2['id']}/activate").json()["is_active"] is True
    assert client.get("/api/v1/profile").json()["id"] == p2["id"]

    profiles = {p["id"]: p for p in client.get("/api/v1/profiles").json()}
    assert profiles[p1["id"]]["is_active"] is False
    assert profiles[p2["id"]]["is_active"] is True

    # 404 sur un profil inexistant
    assert client.get("/api/v1/profile/999999").status_code == 404


def test_matching_selection_cv_flow(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    pid = _upload(
        client,
        "cv.md",
        "# Jean\n## Compétences\n- Python\n- SQL\n- Airflow\n",
        "api_test_prof",
    ).json()["id"]
    # Des offres peuvent déjà exister en base (scraping) : on raisonne en delta.
    before = client.get("/api/v1/job-offers").json()["total"]
    oid = _insert_offer("api-test-001", "Data Engineer", ("Python", "SQL"))

    # Avant matching : l'offre est listée sans score
    listing = client.get("/api/v1/job-offers").json()
    assert listing["total"] == before + 1
    item = next(o for o in listing["items"] if o["id"] == oid)
    assert item["scores"] == []

    # Matching à la demande
    r = client.post("/api/v1/matching/run", json={"job_offer_id": oid})
    assert r.status_code == 200
    match = r.json()
    assert 0 <= match["total_score"] <= 100
    assert match["candidate_profile_id"] == pid

    # Matching contre un profil explicite (non actif ici)
    assert (
        client.post(
            "/api/v1/matching/run",
            json={"job_offer_id": oid, "candidate_profile_id": pid},
        ).status_code
        == 200
    )

    assert client.get("/api/v1/job-offers", params={"company": "Acme"}).json()["total"] == 1

    # La liste expose désormais tous les scores de l'offre, avec le nom du profil.
    # Pas encore de CV généré → has_cv False, has_letter False.
    listing2 = client.get("/api/v1/job-offers").json()
    item = next(o for o in listing2["items"] if o["id"] == oid)
    score = next(
        s
        for s in item["scores"]
        if s["candidate_profile_id"] == pid
        and s["total_score"] == match["total_score"]
        and s["profile_name"] == "api_test_prof"
    )
    assert score["has_cv"] is False
    assert score["has_letter"] is False
    assert score["application_submitted"] is False

    # Génération de CV à la demande
    cv = client.post("/api/v1/cvs/generate", json={"job_offer_id": oid}).json()
    assert cv["score"] == match["total_score"]

    # La liste reflète la présence du CV : has_cv passe à True (indicateur UI).
    listing3 = client.get("/api/v1/job-offers").json()
    item3 = next(o for o in listing3["items"] if o["id"] == oid)
    assert next(
        s for s in item3["scores"] if s["candidate_profile_id"] == pid
    )["has_cv"] is True

    # Détail CV : ``cv_text`` est le Markdown généré par le LLM (mocké).
    # Le mock renvoie ``# [NOM]`` : l'en-tête est retiré et les coordonnées
    # réinjectées côté serveur (nom ``Jean`` extrait du CV uploadé).
    detail_cv = client.get(f"/api/v1/cvs/{cv['cv_id']}").json()
    assert "## Compétences" in detail_cv["cv_text"]
    assert "# [NOM]" not in detail_cv["cv_text"]
    assert "<html" not in detail_cv["cv_text"].lower()
    # Suivi « candidature envoyée » : à False tant que l'utilisateur ne l'a pas marqué.
    assert detail_cv["application_submitted"] is False

    # Téléchargement PDF : le Markdown est converti en PDF côté serveur.
    pdf = client.get(f"/api/v1/cvs/{cv['cv_id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    assert f'filename="cv_{cv["cv_id"]}.pdf"' in pdf.headers["content-disposition"]
    assert pdf.content[:5] == b"%PDF-"

    # Détail d'offre : match + CV + profil résolu
    detail = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail["match"]["total_score"] == match["total_score"]
    assert detail["candidate_profile_id"] == pid
    assert len(detail["cvs"]) == 1
    # Le détail d'offre expose aussi le drapeau (source de l'indicateur UI).
    assert detail["cvs"][0]["application_submitted"] is False

    # Bascule du suivi « candidature envoyée » (état voulu, idempotent).
    r = client.put(
        f"/api/v1/cvs/{cv['cv_id']}/submitted", json={"submitted": True}
    )
    assert r.status_code == 200
    assert r.json()["application_submitted"] is True
    assert (
        client.get(f"/api/v1/job-offers/{oid}").json()["cvs"][0][
            "application_submitted"
        ]
        is True
    )
    # La liste des offres expose aussi le drapeau dans le score du couple.
    listing4 = client.get("/api/v1/job-offers").json()
    item4 = next(o for o in listing4["items"] if o["id"] == oid)
    assert next(
        s for s in item4["scores"] if s["candidate_profile_id"] == pid
    )["application_submitted"] is True
    # Revertible : renvoyer `false` rétablit le bouton côté interface.
    r = client.put(
        f"/api/v1/cvs/{cv['cv_id']}/submitted", json={"submitted": False}
    )
    assert r.status_code == 200
    assert r.json()["application_submitted"] is False
    assert (
        client.get(f"/api/v1/job-offers/{oid}").json()["cvs"][0][
            "application_submitted"
        ]
        is False
    )
    # CV inconnu → 404.
    assert (
        client.put(
            "/api/v1/cvs/999999/submitted", json={"submitted": True}
        ).status_code
        == 404
    )

    # Suppression du CV seul : le matching est conservé, le CV disparaît.
    assert client.delete(f"/api/v1/job-offers/{oid}/cv").status_code == 204
    detail2 = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail2["cvs"] == []
    assert detail2["match"]["total_score"] == match["total_score"]

    # Un second DELETE : plus de CV pour le couple → 404.
    assert client.delete(f"/api/v1/job-offers/{oid}/cv").status_code == 404


def test_letter_generation_flow(client, cleanup):
    """Génération/suppression d'une lettre de motivation.

    Couvre : 409 sans matching, source CV brut du profil (fallback) puis CV
    généré, ``has_letter`` dans la liste, détail de la lettre (nom réinjecté,
    aucun placeholder), ``letters`` dans le détail d'offre, upsert (une seule
    lettre par couple), suppression seule (le matching et le CV sont conservés),
    puis 404 sur un second DELETE.
    """
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    pid = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n- SQL\n- Airflow\n",
        "api_test_prof",
    ).json()["id"]
    oid = _insert_offer("api-test-letter", "Data Engineer", ("Python", "SQL"))

    # Génération de lettre sans matching → 409.
    assert (
        client.post("/api/v1/letters/generate", json={"job_offer_id": oid}).status_code
        == 409
    )

    # Matching, puis lettre SANS CV généré : source = CV brut du profil (fallback).
    r = client.post("/api/v1/matching/run", json={"job_offer_id": oid})
    assert r.status_code == 200
    letter = client.post(
        "/api/v1/letters/generate", json={"job_offer_id": oid}
    ).json()
    assert letter["score"] == r.json()["total_score"]

    # La liste reflète la présence de la lettre : has_letter passe à True.
    listing = client.get("/api/v1/job-offers").json()
    item = next(o for o in listing["items"] if o["id"] == oid)
    score = next(s for s in item["scores"] if s["candidate_profile_id"] == pid)
    assert score["has_letter"] is True

    # Détail lettre : anonyme — ni nom réel (Jean), ni placeholder résiduel.
    detail_letter = client.get(f"/api/v1/letters/{letter['letter_id']}").json()
    assert "Jean" not in detail_letter["letter_text"]
    assert "[NOM]" not in detail_letter["letter_text"]

    # Détail d'offre : la lettre du couple est exposée.
    detail = client.get(f"/api/v1/job-offers/{oid}").json()
    assert len(detail["letters"]) == 1
    assert detail["letters"][0]["id"] == letter["letter_id"]

    # Lettre avec un CV généré existant : source = CV généré, upsert (même id).
    assert (
        client.post("/api/v1/cvs/generate", json={"job_offer_id": oid}).status_code
        == 200
    )
    letter2 = client.post(
        "/api/v1/letters/generate", json={"job_offer_id": oid}
    ).json()
    assert letter2["letter_id"] == letter["letter_id"]

    # Suppression de la lettre seule : le matching et le CV sont conservés.
    assert client.delete(f"/api/v1/job-offers/{oid}/letter").status_code == 204
    detail2 = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail2["letters"] == []
    assert detail2["match"]["total_score"] == r.json()["total_score"]
    assert len(detail2["cvs"]) == 1

    listing2 = client.get("/api/v1/job-offers").json()
    item2 = next(o for o in listing2["items"] if o["id"] == oid)
    assert next(
        s for s in item2["scores"] if s["candidate_profile_id"] == pid
    )["has_letter"] is False

    # Un second DELETE : plus de lettre pour le couple → 404.
    assert client.delete(f"/api/v1/job-offers/{oid}/letter").status_code == 404


def test_delete_match(client, cleanup):
    """Supprimer un matching retire le score ET les CV du couple (offre, profil).

    Un second DELETE renvoie 404.
    """
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    pid = _upload(
        client, "cv.md", RICH_CV, "api_test_del"
    ).json()["id"]
    oid = _insert_offer("api-test-delete-match", "Data Engineer", ("Python", "SQL"))

    # Matching + génération de CV
    r = client.post("/api/v1/matching/run", json={"job_offer_id": oid})
    assert r.status_code == 200
    assert (
        client.post("/api/v1/cvs/generate", json={"job_offer_id": oid}).status_code
        == 200
    )

    detail = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail["match"] is not None
    assert len(detail["cvs"]) == 1

    # Suppression : 204, le score et le CV disparaissent.
    assert (
        client.delete(
            f"/api/v1/matching/{oid}", params={"candidate_profile_id": pid}
        ).status_code
        == 204
    )
    detail2 = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail2["match"] is None
    assert detail2["cvs"] == []
    listing = client.get("/api/v1/job-offers").json()
    item = next(o for o in listing["items"] if o["id"] == oid)
    assert item["scores"] == []

    # Un second DELETE : plus de matching pour ce couple → 404.
    assert (
        client.delete(
            f"/api/v1/matching/{oid}", params={"candidate_profile_id": pid}
        ).status_code
        == 404
    )


def test_offer_list_scores_ordered_by_score_then_date(client, cleanup):
    """La liste des scores est triée par score décroissant puis date décroissante."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p1 = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_s1"
    ).json()
    p2 = _upload(
        client, "cv2.md", "# Paul\n## Compétences\n- Java\n", "api_test_s2"
    ).json()
    p3 = _upload(
        client, "cv3.md", "# Ana\n## Compétences\n- Go\n", "api_test_s3"
    ).json()
    oid = _insert_offer("api-test-scores", "Data Engineer", ("Python", "SQL"))

    # Scores et dates explicites (le LLM est mocké : on insère directement) pour
    # vérifier l'ordre d'affichage :
    #   - p1 (88, plus récent) et p2 (88, plus ancien) -> p1 d'abord (date)
    #   - p3 (60, encore plus récent) -> dernier malgré sa date (score d'abord)
    def _seed(profile_id, score, created):
        match_result_repository.upsert(
            session,
            {
                "job_offer_id": oid,
                "candidate_profile_id": profile_id,
                "total_score": score,
                "score_breakdown": {
                    "title_score": 0.5,
                    "skills_score": 0.5,
                    "experience_score": 0.5,
                    "education_score": 0.5,
                },
                "strengths": [],
                "weaknesses": [],
                "missing_skills": [],
                "created_at": created,
            },
        )

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session_scope() as session:
        _seed(p2["id"], 88, base)
        _seed(p1["id"], 88, base + timedelta(hours=1))
        _seed(p3["id"], 60, base + timedelta(hours=2))

    item = next(
        o
        for o in client.get("/api/v1/job-offers").json()["items"]
        if o["id"] == oid
    )
    assert [s["total_score"] for s in item["scores"]] == [88, 88, 60]
    assert [s["candidate_profile_id"] for s in item["scores"]] == [
        p1["id"],
        p2["id"],
        p3["id"],
    ]
    names = {p["id"]: p["profile_name"] for p in (p1, p2, p3)}
    assert [s["profile_name"] for s in item["scores"]] == [
        names[p1["id"]],
        names[p2["id"]],
        names[p3["id"]],
    ]


def test_offer_list_sorting(client, cleanup):
    """Le tri serveur des offres (sort_by / order) est respecté."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _insert_offer(
        "api-test-srt-b",
        "Béta",
        ("Python",),
        company="Zeta",
        location="Paris - 75",
        ingested_at=base + timedelta(days=2),
    )
    _insert_offer(
        "api-test-srt-a",
        "Alpha",
        ("Python",),
        company="Acme",
        location="Boulogne-Billancourt - 92",
        ingested_at=base + timedelta(days=1),
    )
    _insert_offer(
        "api-test-srt-c",
        "Charlie",
        ("Python",),
        company="Méta",
        location="Lyon - 69",
        ingested_at=base,
    )

    def titles(**params):
        items = client.get(
            "/api/v1/job-offers", params={"limit": 100, **params}
        ).json()["items"]
        return [i["title"] for i in items]

    # Défaut : date de création décroissante (plus récentes d'abord).
    assert titles() == ["Béta", "Alpha", "Charlie"]
    # Titre, croissant puis décroissant.
    assert titles(sort_by="title", order="asc") == ["Alpha", "Béta", "Charlie"]
    assert titles(sort_by="title", order="desc") == ["Charlie", "Béta", "Alpha"]
    # Entreprise décroissante (Zeta > Méta > Acme).
    assert titles(sort_by="company", order="desc") == ["Béta", "Charlie", "Alpha"]
    # Localisation croissante (Boulogne-Billancourt < Lyon < Paris).
    assert titles(sort_by="location", order="asc") == ["Alpha", "Charlie", "Béta"]
    # Date de création croissante.
    assert titles(sort_by="ingested_at", order="asc") == ["Charlie", "Alpha", "Béta"]


def test_offer_list_source_exposed_filterable_sortable(client, cleanup):
    """La source est exposée dans la liste ; filtre `source` et tri `sort_by=source`."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    _insert_offer("api-test-src-a", "Alpha", ("Python",), source="hellowork")
    _insert_offer("api-test-src-b", "Béta", ("Python",), source="example.com")
    _insert_offer("api-test-src-c", "Charlie", ("Python",), source="hellowork")

    def items(**params):
        return client.get(
            "/api/v1/job-offers", params={"limit": 100, **params}
        ).json()["items"]

    # La liste expose la source de chaque offre.
    all_items = items()
    assert {i["title"]: i["source"] for i in all_items} == {
        "Alpha": "hellowork",
        "Béta": "example.com",
        "Charlie": "hellowork",
    }

    # Filtre partiel insensible à la casse sur la source (ordre par défaut :
    # ingestion décroissante → Charlie puis Alpha).
    assert [i["title"] for i in items(source="hellowork")] == ["Charlie", "Alpha"]
    assert [i["title"] for i in items(source="EXAMPLE")] == ["Béta"]

    # Tri par source : croissant (example.com < hellowork, les hellowork entre
    # elles par id décroissant), puis décroissant.
    assert [i["title"] for i in items(sort_by="source", order="asc")] == [
        "Béta",
        "Charlie",
        "Alpha",
    ]
    assert [i["title"] for i in items(sort_by="source", order="desc")] == [
        "Charlie",
        "Alpha",
        "Béta",
    ]


def test_offer_detail_targets_profile(client, cleanup):
    """Le détail d'une offre cible un profil via ?candidate_profile_id=."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p1 = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof"
    ).json()
    assert p1["is_active"] is True
    # p2 (inactif) : CV riche pour dépasser le seuil de génération de CV.
    p2 = _upload(client, "cv2.md", RICH_CV, "api_test_prof2").json()
    assert p2["is_active"] is False

    oid = _insert_offer("api-test-003", "Data Engineer", ("Python", "SQL"))

    # Matching contre le profil inactif p2, explicitement.
    r = client.post(
        "/api/v1/matching/run",
        json={"job_offer_id": oid, "candidate_profile_id": p2["id"]},
    )
    assert r.status_code == 200
    assert r.json()["candidate_profile_id"] == p2["id"]

    # Détail ciblé sur p2 : le match de p2 est renvoyé.
    d2 = client.get(
        f"/api/v1/job-offers/{oid}", params={"candidate_profile_id": p2["id"]}
    ).json()
    assert d2["candidate_profile_id"] == p2["id"]
    assert d2["match"]["candidate_profile_id"] == p2["id"]

    # Détail par défaut : profil actif p1 (jamais matché pour cette offre → null).
    d1 = client.get(f"/api/v1/job-offers/{oid}").json()
    assert d1["candidate_profile_id"] == p1["id"]
    assert d1["match"] is None

    # Profil inexistant : pas de 404, match null et id renvoyé tel quel.
    d0 = client.get(
        f"/api/v1/job-offers/{oid}", params={"candidate_profile_id": 999999}
    ).json()
    assert d0["candidate_profile_id"] == 999999
    assert d0["match"] is None


def test_stats(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    before = client.get("/api/v1/stats").json()["offers_total"]

    _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof"
    )
    oid = _insert_offer("api-test-001", "Data Engineer", ("Python", "SQL"))
    client.post("/api/v1/matching/run", json={"job_offer_id": oid})

    stats = client.get("/api/v1/stats").json()
    assert stats["profile_loaded"] is True
    assert stats["offers_total"] == before + 1
    assert stats["offers_with_cv"] == 0


def test_repository_active_is_single(cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    def _profile_dict(name):
        d = CandidateProfile(
            profile_name=name, headline="H", skills=["Python"]
        ).to_persist_dict()
        d["is_active"] = False
        return d

    with session_scope() as session:
        p1 = candidate_profile_repository.insert(session, _profile_dict("api_test_prof"))
        p2 = candidate_profile_repository.insert(session, _profile_dict("api_test_prof2"))

    with session_scope() as session:
        assert candidate_profile_repository.set_active(session, p1) is True
        assert candidate_profile_repository.get_active(session).id == p1
    with session_scope() as session:
        assert candidate_profile_repository.set_active(session, p2) is True
        assert candidate_profile_repository.get_active(session).id == p2
    with session_scope() as session:
        # Un seul actif : p1 est revenu à False
        actives = [
            r for r in candidate_profile_repository.list_all(session) if r.is_active
        ]
        assert [r.id for r in actives] == [p2]


def test_profile_raw_content(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    content = "# Jean\n## Compétences\n- Python\n"
    p = _upload(client, "cv.md", content, "api_test_prof").json()

    # Le détail (POST et GET) expose le contenu brut
    assert p["raw_content"] == content
    assert client.get(f"/api/v1/profile/{p['id']}").json()["raw_content"] == content

    # La version Markdown est exposée telle quelle pour un CV Markdown
    assert p["raw_content_markdown"] == content

    # Un CV HTML uploadé est converti en Markdown
    html = "<html><body><h1>Jean</h1><ul><li>Python</li></ul></body></html>"
    p_html = _upload(client, "cv.html", html, "api_test_html").json()
    md = p_html["raw_content_markdown"]
    assert "# Jean" in md and "Python" in md

    # La liste reste légère : pas de raw_content
    profiles = {x["id"]: x for x in client.get("/api/v1/profiles").json()}
    assert "raw_content" not in profiles[p["id"]]


def test_profile_rename(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof"
    ).json()
    p2 = _upload(
        client, "cv2.md", "# Paul\n## Compétences\n- Java\n", "api_test_prof2"
    ).json()

    # Renommage OK, nom trimé
    r = client.patch(
        f"/api/v1/profiles/{p['id']}", json={"profile_name": "  api_test_renamed  "}
    )
    assert r.status_code == 200
    assert r.json()["profile_name"] == "api_test_renamed"

    # No-op : renommer vers le même nom
    assert (
        client.patch(
            f"/api/v1/profiles/{p['id']}", json={"profile_name": "api_test_renamed"}
        ).status_code
        == 200
    )

    # 409 : nom déjà pris par un autre profil
    assert (
        client.patch(
            f"/api/v1/profiles/{p2['id']}", json={"profile_name": "api_test_renamed"}
        ).status_code
        == 409
    )

    # 404 : profil inexistant
    assert (
        client.patch("/api/v1/profiles/999999", json={"profile_name": "x"}).status_code
        == 404
    )

    # 422 : nom vide après trim
    assert (
        client.patch(
            f"/api/v1/profiles/{p['id']}", json={"profile_name": "   "}
        ).status_code
        == 422
    )


def test_profile_deactivate(client, cleanup):
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    p = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof"
    ).json()
    assert p["is_active"] is True

    # Le profil actif ne peut pas être désactivé (409)
    r = client.put(f"/api/v1/profiles/{p['id']}/deactivate")
    assert r.status_code == 409

    # Un second profil : l'activer désactive automatiquement le premier
    p2 = _upload(
        client, "cv2.md", "# Paul\n## Compétences\n- Java\n", "api_test_prof2"
    ).json()
    assert p2["is_active"] is False
    assert (
        client.put(f"/api/v1/profiles/{p2['id']}/activate").json()["is_active"] is True
    )
    assert client.get("/api/v1/profile").json()["id"] == p2["id"]

    # p (inactif) peut être désactivé sans toucher au profil actif
    r = client.put(f"/api/v1/profiles/{p['id']}/deactivate")
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert client.get("/api/v1/profile").json()["id"] == p2["id"]

    # 404 sur un profil inexistant
    assert client.put("/api/v1/profiles/999999/deactivate").status_code == 404

    # Réactivation possible
    assert (
        client.put(f"/api/v1/profiles/{p['id']}/activate").json()["is_active"] is True
    )


def test_offer_archive_flow(client, cleanup):
    """Archiver retire l'offre de la liste par défaut ; désarchiver la ramène."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    oid = _insert_offer("api-test-arc", "Data Engineer", ("Python", "SQL"))

    # Archive
    r = client.put(f"/api/v1/job-offers/{oid}/archived", json={"archived": True})
    assert r.status_code == 200
    body = r.json()
    assert body["archived"] is True
    assert body["archived_at"] is not None

    # Absente de la liste par défaut, présente dans la liste des archivées
    default_ids = [o["id"] for o in client.get("/api/v1/job-offers").json()["items"]]
    assert oid not in default_ids
    archived = client.get("/api/v1/job-offers", params={"archived": True}).json()
    assert any(o["id"] == oid and o["archived"] is True for o in archived["items"])

    # Le détail expose l'état archivé
    detail = client.get(f"/api/v1/job-offers/{oid}").json()
    assert detail["archived"] is True
    assert detail["archived_at"] is not None

    # Désarchive
    r = client.put(f"/api/v1/job-offers/{oid}/archived", json={"archived": False})
    assert r.status_code == 200
    assert r.json()["archived"] is False
    assert r.json()["archived_at"] is None
    assert oid in [o["id"] for o in client.get("/api/v1/job-offers").json()["items"]]

    # 404 sur une offre inexistante
    assert (
        client.put("/api/v1/job-offers/999999/archived", json={"archived": True}).status_code
        == 404
    )


def test_offer_list_archived_filter(client, cleanup):
    """Le filtre ``archived`` de la liste sépare actives et archivées."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    oid_active = _insert_offer("api-test-arc-a", "Actif", ("Python",))
    oid_archived = _insert_offer("api-test-arc-b", "Archivé", ("Python",))
    _set_archived(oid_archived)

    def titles(**params):
        items = client.get(
            "/api/v1/job-offers", params={"limit": 100, **params}
        ).json()["items"]
        return [i["title"] for i in items]

    assert titles() == ["Actif"]
    assert titles(archived=True) == ["Archivé"]
    assert oid_active not in [
        o["id"] for o in client.get("/api/v1/job-offers", params={"archived": True}).json()["items"]
    ]


def test_offer_detail_exposes_scores(client, cleanup):
    """Le détail d'une offre expose ses scores (profils matchés + nom)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    pid = _upload(
        client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof"
    ).json()["id"]
    oid = _insert_offer("api-test-arc", "Data Engineer", ("Python", "SQL"))
    client.post("/api/v1/matching/run", json={"job_offer_id": oid})

    detail = client.get(f"/api/v1/job-offers/{oid}").json()
    assert any(
        s["candidate_profile_id"] == pid
        and s["profile_name"] == "api_test_prof"
        for s in detail["scores"]
    )


def test_archived_offer_actions_blocked(client, cleanup):
    """Les actions matching, suppression de matching et générations (CV, lettre) sont refusées (409)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    _upload(client, "cv.md", "# Jean\n## Compétences\n- Python\n", "api_test_prof")
    oid = _insert_offer("api-test-arc", "Data Engineer", ("Python", "SQL"))
    client.post("/api/v1/matching/run", json={"job_offer_id": oid})
    _set_archived(oid)

    assert (
        client.post("/api/v1/cvs/generate", json={"job_offer_id": oid}).status_code
        == 409
    )
    assert (
        client.post("/api/v1/letters/generate", json={"job_offer_id": oid}).status_code
        == 409
    )
    assert (
        client.post("/api/v1/matching/run", json={"job_offer_id": oid}).status_code
        == 409
    )
    assert client.delete(f"/api/v1/matching/{oid}").status_code == 409
    assert client.delete(f"/api/v1/job-offers/{oid}/letter").status_code == 409
    assert client.delete(f"/api/v1/job-offers/{oid}/cv").status_code == 409


def _neighbors(client, offer_id):
    """Retourne (previous_offer_id, next_offer_id) du détail d'une offre."""
    data = client.get(f"/api/v1/job-offers/{offer_id}").json()
    assert data["id"] == offer_id
    return data["previous_offer_id"], data["next_offer_id"]


def test_offer_neighbors(client, cleanup):
    """Le détail expose les offres précédente/suivante (ingested_at DESC, id DESC)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    oid_a = _insert_offer("api-test-nbr-a", "Récente", ("Python",), ingested_at=base + timedelta(days=2))
    oid_b = _insert_offer("api-test-nbr-b", "Milieu", ("Python",), ingested_at=base + timedelta(days=1))
    oid_c = _insert_offer("api-test-nbr-c", "Base 1", ("Python",), ingested_at=base)
    oid_d = _insert_offer("api-test-nbr-d", "Base 2", ("Python",), ingested_at=base)
    oid_e = _insert_offer("api-test-nbr-e", "Ancienne", ("Python",), ingested_at=base - timedelta(days=1))
    # Ordre de liste attendu (ingested_at DESC, id DESC) : A, B, D, C, E.

    # Voisin de droite / de gauche dans cet ordre.
    assert _neighbors(client, oid_b) == (oid_a, oid_d)
    # Tie-break par id à date égale : D (id > C) précède C.
    assert _neighbors(client, oid_c) == (oid_d, oid_e)
    # Extrémités : pas de voisine au-delà.
    assert _neighbors(client, oid_a) == (None, oid_b)
    assert _neighbors(client, oid_e) == (oid_c, None)

    # Confinement : les voisines sont restreintes au même ensemble archivé/actif.
    _set_archived(oid_a)
    # B : A (archivée) exclue → plus de voisine de gauche.
    assert _neighbors(client, oid_b) == (None, oid_d)
    # A (archivée) : ses voisines sont uniquement parmi les offres archivées.
    assert _neighbors(client, oid_a) == (None, None)

    # Offre inexistante → 404 (pas de voisines exposées).
    assert client.get("/api/v1/job-offers/999999").status_code == 404


def test_offer_from_url_flow(client, cleanup, monkeypatch):
    """Ingestion d'une offre depuis une URL : 201, reflet dans la liste, 409, 422.

    Le fetch Playwright est mocké (pas de navigateur dans les tests) ; le LLM
    d'extraction est servi par le fixture autouse ``_mock_llm`` (branche
    ``=== OFFRE DEPUIS URL ===``, dict single sans URL individuelle → chemin
    « offre unique »).
    """
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    monkeypatch.setattr(
        URLScraper,
        "fetch_text",
        staticmethod(lambda url: "<html><body>Data Engineer chez Acme</body></html>"),
    )

    before = client.get("/api/v1/job-offers").json()["total"]

    url = "https://example.com/from-url-test/1"
    r = client.post("/api/v1/job-offers/from-url", json={"url": url})
    assert r.status_code == 201
    body = r.json()
    assert body["added"] == 1
    assert body["already_present"] == 0
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["title"] == "Data Engineer H/F"
    assert offer["company"] == "Acme"
    assert offer["location"] == "Paris - 75"
    assert offer["contract_type"] == "CDI"
    assert offer["url"] == url
    assert offer["archived"] is False
    assert offer["scores"] == []

    # Source = domaine de l'URL (pipeline d'ingestion existant), exposée au détail.
    oid = offer["id"]
    assert client.get(f"/api/v1/job-offers/{oid}").json()["source"] == "example.com"

    # L'offre apparaît dans la liste des offres actives (total +1).
    listing = client.get("/api/v1/job-offers").json()
    assert listing["total"] == before + 1
    assert any(o["id"] == oid for o in listing["items"])

    # Second POST de la même URL → 409 (déjà en base).
    r2 = client.post("/api/v1/job-offers/from-url", json={"url": url})
    assert r2.status_code == 409

    # URL invalide (schéma non-http(s)) → 422, rien n'est inséré.
    for bad in ("pas une url", "file:///etc/passwd"):
        assert (
            client.post("/api/v1/job-offers/from-url", json={"url": bad}).status_code
            == 422
        )
    assert client.get("/api/v1/job-offers").json()["total"] == before + 1


def _single_offer_payload(**overrides):
    """Réponse « offre unique » du LLM pour un fetch individuel."""
    payload = {
        "title": "Data Engineer",
        "company": "Acme",
        "location": "Paris - 75",
        "contract_type": "CDI",
        "description": "Pipelines Python",
        "published_date": "2026-05-22",
    }
    payload.update(overrides)
    return {"page_type": "single", "offer": payload}


def _list_payload(*urls):
    """Réponse « liste d'offres » du LLM : uniquement les URLs."""
    return {"page_type": "list", "offers": [{"url": u} for u in urls]}


def _mock_url_llm_queue(monkeypatch, payloads):
    """Remplace ``URL_SCRAPER_LLM`` par des réponses JSON déterministes
    consommées dans l'ordre : la classification de la page (liste), puis une
    réponse « offre unique » par fetch individuel."""

    queue = list(payloads)

    def invoke(_messages):
        if not queue:
            raise AssertionError("URL_SCRAPER_LLM invoqué plus que prévu")
        return SimpleNamespace(content=json.dumps(queue.pop(0), ensure_ascii=False))

    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", SimpleNamespace(invoke=invoke))


def test_offer_from_url_list_flow(client, cleanup, monkeypatch):
    """Liste d'offres depuis une URL : 201 avec plusieurs offres, re-POST →
    ``added==0`` / ``already_present==2`` (pas de 409 sur une liste).

    Le LLM ne renvoie que les **URLs** de la liste ; chaque URL nouvelle est
    ensuite récupérée individuellement (fetch + extraction mono-offre), dans
    l'ordre de la page.
    """
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    list_url = "https://example.com/from-url-test/list"
    offer_urls = [
        "https://example.com/from-url-test/list/1",
        "https://example.com/from-url-test/list/2",
    ]

    def _fetch_text(url):
        if url == list_url:
            return "<html><body>Liste de deux offres chez Acme</body></html>"
        if url == offer_urls[0]:
            return "<html><body>Offre Data Engineer</body></html>"
        if url == offer_urls[1]:
            return "<html><body>Offre Data Analyst</body></html>"
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(URLScraper, "fetch_text", staticmethod(_fetch_text))
    _mock_url_llm_queue(
        monkeypatch,
        [
            _list_payload(*offer_urls),
            _single_offer_payload(
                title="Data Engineer",
                company="Acme",
                location="Paris - 75",
                contract_type="CDI",
                description="Pipelines Python",
            ),
            _single_offer_payload(
                title="Data Analyst",
                company="Acme",
                location="Lyon",
                contract_type="CDI",
                description="SQL et dashboards",
            ),
        ],
    )

    before = client.get("/api/v1/job-offers").json()["total"]
    r = client.post(
        "/api/v1/job-offers/from-url", json={"url": list_url, "max_offers": 2}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["added"] == 2
    assert body["already_present"] == 0
    assert len(body["offers"]) == 2
    # Chaque offre garde son URL individuelle (clé de dédoublonnage).
    assert {o["url"] for o in body["offers"]} == set(offer_urls)

    listing = client.get("/api/v1/job-offers").json()
    assert listing["total"] == before + 2

    # Re-POST de la même liste : les URLs sont déjà en base → sautées sans fetch
    # individuel, aucune insertion ni récupération (`offers` vide), compteurs
    # « déjà en base », PAS de 409 (le chemin liste ne déclenche pas le doublon
    # d'offre unique).
    _mock_url_llm_queue(monkeypatch, [_list_payload(*offer_urls)])
    r2 = client.post(
        "/api/v1/job-offers/from-url", json={"url": list_url, "max_offers": 2}
    )
    assert r2.status_code == 201
    body2 = r2.json()
    assert body2["added"] == 0
    assert body2["already_present"] == 2
    assert body2["offers"] == []
    assert client.get("/api/v1/job-offers").json()["total"] == before + 2


def test_offer_from_url_max_offers_bounds(client, monkeypatch):
    """``max_offers`` hors bornes (0, 21) → 422, sans fetch ni insertion."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    # Le fetch ne doit pas être atteint : la validation Pydantic échoue d'abord.
    monkeypatch.setattr(
        URLScraper,
        "fetch_text",
        staticmethod(lambda url: (_ for _ in ()).throw(AssertionError("non appelé"))),
    )
    for bad in (0, 21):
        r = client.post(
            "/api/v1/job-offers/from-url",
            json={"url": "https://example.com/from-url-test/bound", "max_offers": bad},
        )
        assert r.status_code == 422


def test_offer_from_url_llm_unavailable(client, cleanup, monkeypatch):
    """Sans LLM d'extraction, POST /job-offers/from-url → 502, sans insertion."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    monkeypatch.setattr(
        URLScraper,
        "fetch_text",
        staticmethod(lambda url: "<html><body>Data Engineer chez Acme</body></html>"),
    )
    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", None)

    before = client.get("/api/v1/job-offers").json()["total"]
    r = client.post(
        "/api/v1/job-offers/from-url",
        json={"url": "https://example.com/from-url-test/llm"},
    )
    assert r.status_code == 502
    assert client.get("/api/v1/job-offers").json()["total"] == before


def test_offer_from_url_with_source_flow(client, cleanup):
    """Ingestion depuis le contenu collé (champ `source` de POST /job-offers/from-url) :
    201, reflet dans la liste, 409, 422 — sans aucun fetch Playwright.

    Le LLM d'extraction est servi par le fixture autouse ``_mock_llm`` ; la
    conversion HTML→texte et l'extraction mono-offre remplacent la
    récupération de la page (l'URL fournie n'est jamais récupérée).
    """
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    before = client.get("/api/v1/job-offers").json()["total"]

    url = "https://example.com/from-source-test/1"
    r = client.post(
        "/api/v1/job-offers/from-url",
        json={"url": url, "source": "<html><body><p>Data Engineer</p></body></html>"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["added"] == 1
    assert body["already_present"] == 0
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["title"] == "Data Engineer H/F"
    assert offer["company"] == "Acme"
    assert offer["location"] == "Paris - 75"
    assert offer["contract_type"] == "CDI"
    assert offer["url"] == url
    assert offer["archived"] is False
    assert offer["scores"] == []

    # Source d'ingestion = domaine de l'URL soumise (clé, jamais récupérée).
    oid = offer["id"]
    assert client.get(f"/api/v1/job-offers/{oid}").json()["source"] == "example.com"

    # L'offre apparaît dans la liste des offres actives (total +1).
    listing = client.get("/api/v1/job-offers").json()
    assert listing["total"] == before + 1
    assert any(o["id"] == oid for o in listing["items"])

    # Second POST de la même URL → 409 (clé de dédoublonnage), même avec un
    # autre contenu : l'URL prime sur le contenu collé.
    r2 = client.post(
        "/api/v1/job-offers/from-url",
        json={"url": url, "source": "autre contenu"},
    )
    assert r2.status_code == 409

    # URL invalide (non-http(s)) → 422 via la normalisation, rien n'est inséré.
    assert (
        client.post(
            "/api/v1/job-offers/from-url",
            json={"url": "pas une url", "source": "contenu"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/job-offers/from-url",
            json={"url": "", "source": "contenu"},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/job-offers").json()["total"] == before + 1


def test_offer_from_url_with_source_too_large(client, cleanup):
    """Contenu collé au-delà de ``SOURCE_MAX_CHARS`` → 413, rien n'est inséré."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    before = client.get("/api/v1/job-offers").json()["total"]
    r = client.post(
        "/api/v1/job-offers/from-url",
        json={
            "url": "https://example.com/from-source-test/big",
            "source": "x" * (SOURCE_MAX_CHARS + 1),
        },
    )
    assert r.status_code == 413
    assert client.get("/api/v1/job-offers").json()["total"] == before


def test_offer_from_url_with_source_not_single(client, cleanup, monkeypatch):
    """Le source d'une page de recherche (liste) collé → 422 « pas une offre » :
    le contenu collé est mono-offre (les listes restent au fetch Playwright)."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    _mock_url_llm_queue(monkeypatch, [{"page_type": "none", "reason": "liste d'offres"}])
    before = client.get("/api/v1/job-offers").json()["total"]

    r = client.post(
        "/api/v1/job-offers/from-url",
        json={
            "url": "https://example.com/from-source-test/list",
            "source": "Deux offres chez Acme",
        },
    )
    assert r.status_code == 422
    assert client.get("/api/v1/job-offers").json()["total"] == before


def test_offer_from_url_with_source_llm_unavailable(client, cleanup, monkeypatch):
    """Sans LLM d'extraction, POST /job-offers/from-url avec `source` → 502, sans insertion."""
    if not _db_up():
        pytest.skip("Base PostgreSQL applicative indisponible")

    monkeypatch.setattr(score_engine, "URL_SCRAPER_LLM", None)
    before = client.get("/api/v1/job-offers").json()["total"]

    r = client.post(
        "/api/v1/job-offers/from-url",
        json={
            "url": "https://example.com/from-source-test/llm",
            "source": "Data Engineer",
        },
    )
    assert r.status_code == 502
    assert client.get("/api/v1/job-offers").json()["total"] == before
