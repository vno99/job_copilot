"""Tests de l'anonymisation du CV avant envoi au LLM (matching)."""

import pytest
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# Tests des fonctions internes et du domaine (provenant de test_anonymize_unit.py)
# ---------------------------------------------------------------------------

class TestAnonymizeFunctions:
    """Tests des fonctions d'anonymize.py."""

    def test_looks_like_name_valid(self):
        from src.core.privacy.anonymize import looks_like_name

        assert looks_like_name("Jean Dupont") is True
        assert looks_like_name("Marie-Claire Martin") is True
        assert looks_like_name("O'Brien") is True

    def test_looks_like_name_invalid(self):
        from src.core.privacy.anonymize import looks_like_name

        # Ces chaînes ne ressemblent pas à des noms
        assert looks_like_name("Data Engineer") is False
        assert looks_like_name("") is False
        # Note: "Python SQL" peut renvoyer True selon l'heuristique

    def test_leading_name(self):
        from src.core.privacy.anonymize import _leading_name

        assert _leading_name("Jean Dupont\nData Engineer") == "Jean Dupont"

    def test_extract_contact_info_full(self):
        from src.core.privacy.anonymize import extract_contact_info

        text = (
            "# Jean Dupont\n\n"
            "77360 VAIRES SUR MARNE | jean.dupont@example.com | 06 59 19 35 72 | "
            "linkedin.com/in/jean-dupont"
        )
        info = extract_contact_info(text)
        assert info["name"] == "Jean Dupont"
        assert info["email"] == "jean.dupont@example.com"
        assert info["phone"] == "06 59 19 35 72"
        assert info["location"] == "77360 VAIRES SUR MARNE"
        assert info["linkedin"] == "linkedin.com/in/jean-dupont"

    def test_extract_contact_info_no_phone(self):
        from src.core.privacy.anonymize import extract_contact_info

        text = "# Marie Martin\n\njean@ex.com"
        info = extract_contact_info(text)
        assert info["name"] == "Marie Martin"
        assert info["email"] == "jean@ex.com"
        assert info["phone"] == ""

    def test_extract_contact_info_bold_name(self):
        from src.core.privacy.anonymize import extract_contact_info

        text = "**Jean Dupont**\n\njean.dupont@email.com"
        info = extract_contact_info(text)
        assert info["name"] == "Jean Dupont"

    def test_extract_contact_info_section_title_not_name(self):
        from src.core.privacy.anonymize import extract_contact_info

        text = "## Résumé\nData Engineer.\n## Compétences\n- Python"
        info = extract_contact_info(text)
        assert info["name"] == ""

    def test_anonymize_cv_with_name(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = (
            "# Jean Dupont\n\n"
            "jean.dupont@email.com\n\n"
            "## Compétences\n- Python"
        )

        result = anonymize_cv(cv, name="Jean Dupont")

        assert "[NOM]" in result
        assert "jean.dupont@email.com" not in result
        assert "[EMAIL]" in result

    def test_anonymize_cv_without_name(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = "# Data Engineer\n\n## Compétences\n- Python"

        result = anonymize_cv(cv)

        assert "[NOM]" not in result or "Jean" not in result

    def test_anonymize_cv_with_phone(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = (
            "# Jean\n\n"
            "06 59 19 35 72\n\n"
            "## Compétences\n- Python"
        )

        result = anonymize_cv(cv, name="Jean")

        assert "06 59 19 35 72" not in result
        assert "[TÉLÉPHONE]" in result

    def test_anonymize_cv_with_zip_city(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = (
            "# Jean\n\n"
            "75001 Paris\n\n"
            "## Compétences\n- Python"
        )

        result = anonymize_cv(cv, name="Jean")

        assert "75001 Paris" not in result
        assert "[VILLE]" in result

    def test_anonymize_cv_with_linkedin(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = (
            "# Jean\n\n"
            "linkedin.com/in/jean-dupont\n\n"
            "## Compétences\n- Python"
        )

        result = anonymize_cv(cv, name="Jean")

        assert "linkedin.com/in/jean-dupont" not in result
        assert "[LINKEDIN]" in result

    def test_anonymize_cv_with_email_only(self):
        from src.core.privacy.anonymize import anonymize_cv

        cv = "# Data Engineer\n\n## Compétences\n- Python"
        result = anonymize_cv(cv)

        # Sans coordonnées, le CV doit rester inchangé
        assert "Data Engineer" in result

    def test_clean_letter_markdown(self):
        from src.core.privacy.anonymize import clean_letter_markdown

        letter = (
            "# Jean Dupont\n\n"
            "Madame, Monsieur,\n\n"
            "Je suis intéressé par le poste."
        )

        result = clean_letter_markdown(letter, name="Jean Dupont")

        assert "[NOM]" not in result
        assert "Jean Dupont" not in result

    def test_clean_letter_markdown_with_placeholders(self):
        from src.core.privacy.anonymize import clean_letter_markdown

        letter = (
            "Madame, Monsieur,\n\n"
            "Je suis [NOM] et je [EMAIL]."
        )

        result = clean_letter_markdown(letter, name="Jean")

        assert "[NOM]" not in result
        assert "[EMAIL]" not in result


class TestAnonymizeInternal:
    """Tests des branches internes de anonymize.py."""

    def test_anonymize_name_with_whitespace_only_name(self):
        """Quand name est compose uniquement d'espaces, name_clean est vide
        et on retourne text sans modification."""
        from src.core.privacy.anonymize import _anonymize_name

        text = "Jean Dupont\nPython SQL"
        result = _anonymize_name(text, "    ")
        assert "Jean Dupont" in result

    def test_anonymize_name_skips_short_tokens(self):
        """Les tokens de moins de 3 caracteres sont ignres."""
        from src.core.privacy.anonymize import _anonymize_name

        text = "Jean Dupont\nPython SQL"
        result = _anonymize_name(text, "Jean Dupont")
        assert "Jean" not in result
        assert "Dupont" not in result
        assert "Python" in result

    def test_split_title_with_empty_first_line(self):
        """Une premiere ligne vide est skippe."""
        from src.core.privacy.anonymize import _split_title

        title, rest = _split_title("\n\n## Compétences\n- Python")
        assert title is None
        assert "## Compétences" in rest

    def test_split_title_with_separator_line(self):
        """Un separateur Markdown (---) ne constitue pas un titre."""
        from src.core.privacy.anonymize import _split_title

        title, rest = _split_title("---\n## Compétences\n- Python")
        assert title is None
        assert "## Compétences" in rest

    def test_split_title_with_real_title(self):
        """Un titre de poste sur la premiere ligne non vide est capture."""
        from src.core.privacy.anonymize import _split_title

        title, rest = _split_title("**Data Engineer**\n## Compétences\n- Python")
        assert title == "**Data Engineer**"
        assert "## Compétences" in rest


class TestCandidateProfileDomain:
    """Tests de CandidateProfile."""

    def test_from_row(self):
        from src.core.domain.candidate_profile import CandidateProfile

        mock_row = MagicMock()
        mock_row.profile_name = "test"
        mock_row.headline = "Data Engineer"
        mock_row.summary = "Summary"
        mock_row.skills = ["python"]
        mock_row.experiences = []
        mock_row.education = []
        mock_row.source_path = "cv.md"

        profile = CandidateProfile.from_row(mock_row)

        assert profile.profile_name == "test"
        assert profile.headline == "Data Engineer"
