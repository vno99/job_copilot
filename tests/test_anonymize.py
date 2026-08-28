"""Tests de l'anonymisation du CV avant envoi au LLM (matching)."""

from src.core.privacy.anonymize import _extract_name, anonymize_cv


def test_removes_email():
    assert anonymize_cv("Contact : nouane_v@hotmail.com") == "Contact : [EMAIL]"


def test_removes_linkedin_url_and_anchor():
    text = (
        "[linkedin.com/in/victor-nouane/]"
        "(https://www.linkedin.com/in/victor-nouane/)"
    )
    out = anonymize_cv(text)
    assert "linkedin.com" not in out.lower()
    assert "[LINKEDIN]" in out


def test_removes_phone_spaced():
    assert anonymize_cv("Tel : 06 59 19 35 72") == "Tel : [TÉLÉPHONE]"


def test_removes_phone_compact():
    assert anonymize_cv("Portable : 0659193572") == "Portable : [TÉLÉPHONE]"


def test_removes_postal_code_and_city():
    assert anonymize_cv("77360 VAIRES SUR MARNE") == "[VILLE]"


def test_removes_name_from_headline():
    text = "**NOUANE Victor**\n\nPython / SQL"
    out = anonymize_cv(text, name="NOUANE Victor")
    assert "NOUANE" not in out
    assert "Victor" not in out
    assert "[NOM]" in out
    # Le reste du CV est conservé.
    assert "Python" in out
    assert "SQL" in out


def test_title_headline_does_not_hide_real_name():
    """Un intitulé de poste passé en ``name`` (ex. headline = titre en gras du
    CV) ne doit pas désactiver la détection automatique du vrai nom : sans
    cette garde, le nom réel resterait en clair dans le texte envoyé au LLM
    (fuite PII)."""
    text = "**Data Engineer — Acme**\n\nJean Dupont\nPython / SQL"
    out = anonymize_cv(text, name="Data Engineer — Acme")
    assert "Jean" not in out
    assert "Dupont" not in out
    assert "[NOM]" in out
    assert "Python" in out


def test_extract_name_skips_pure_title():
    """Une ligne en gras/heading qui est un intitulé de poste (pas un nom)
    n'est pas traitée comme le nom du candidat."""
    assert _extract_name("**Data Engineer — Acme**\n\nPython / SQL") == ""
    assert _extract_name("# Ingénieur Full Stack\n\nPython / SQL") == ""


def test_extract_name_keeps_leading_name_in_combined_heading():
    """Une ligne « Nom — Poste » (en gras ou heading) renvoie le nom, pas
    l'intitulé complet — le nom reste détectable sur une ligne combinée."""
    assert _extract_name("**Jean Dupont — Data Engineer**\n\nPython") == "Jean Dupont"
    assert _extract_name("# Jean Dupont - Data Engineer\n\nPython") == "Jean Dupont"


def test_keeps_work_dates():
    text = "01/2022 — 06/2025"
    assert anonymize_cv(text, name="") == text


def test_keeps_technical_content():
    text = "Pipelines avec Python, Airflow, dbt et PostgreSQL."
    assert anonymize_cv(text, name="Victor") == text


def test_empty_text():
    assert anonymize_cv("") == ""
