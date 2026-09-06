"""Tests unitaires pour letter_generator_llm.py (lignes manquantes)."""
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


class TestRewriteLetterHuman:
    """Tests de _rewrite_letter_human."""

    def test_rewrite_letter_human_no_api_key(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            _rewrite_letter_human,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        monkeypatch.setattr(score_engine, "HUMANIZE_LLM", None)

        with pytest.raises(LetterGenerationError, match="OPENROUTER_API_KEY"):
            _rewrite_letter_human(
                {"title": "Dev"},
                {"raw_cv": "# Jean"},
                "Madame, Monsieur"
            )

    def test_rewrite_letter_human_empty_response(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            _rewrite_letter_human,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(content="   ")
        monkeypatch.setattr(score_engine, "HUMANIZE_LLM", mock_llm)

        with pytest.raises(LetterGenerationError, match="vide"):
            _rewrite_letter_human(
                {"title": "Dev"},
                {"raw_cv": "# Jean"},
                "Madame, Monsieur"
            )

    def test_rewrite_letter_human_api_error(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            _rewrite_letter_human,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API down")
        monkeypatch.setattr(score_engine, "HUMANIZE_LLM", mock_llm)

        with pytest.raises(LetterGenerationError, match="erreur API"):
            _rewrite_letter_human(
                {"title": "Dev"},
                {"raw_cv": "# Jean"},
                "Madame, Monsieur"
            )

    def test_rewrite_letter_human_success(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import _rewrite_letter_human
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(
            content="Madame, Monsieur,\n\nRéécrite avec style.\n\nCordialement,"
        )
        monkeypatch.setattr(score_engine, "HUMANIZE_LLM", mock_llm)

        result = _rewrite_letter_human(
            {"title": "Dev"},
            {"raw_cv": "# Jean"},
            "Madame, Monsieur"
        )

        assert "Réécrite" in result
        assert mock_llm.invoke.call_count == 1


class TestHumanizeLetterMarkdown:
    """Tests de humanize_letter_markdown (two-pass)."""

    def test_humanize_letter_fallback_on_pass2_failure(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            humanize_letter_markdown,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        # Pass 1 réussie
        monkeypatch.setattr(
            "src.core.scoring.letter_generator_llm.generate_letter_markdown",
            lambda job, profile: "Lettre pass 1"
        )

        # Pass 2 échoue
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API down")
        monkeypatch.setattr(score_engine, "HUMANIZE_LLM", mock_llm)

        result = humanize_letter_markdown({"title": "Dev"}, {"raw_cv": "# Jean"})

        assert result == "Lettre pass 1"


# ---------------------------------------------------------------------------
# generate_letter_markdown (rappels des lignes déjà couvertes)
# ---------------------------------------------------------------------------

class TestGenerateLetterMarkdown:
    """Tests de generate_letter_markdown."""

    def test_generate_letter_markdown_success(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import generate_letter_markdown
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(
            content="Madame, Monsieur,\n\nContenu de la lettre.\n\nCordialement,"
        )
        monkeypatch.setattr(score_engine, "GENERATION_LLM", mock_llm)

        result = generate_letter_markdown(
            {"title": "Data Engineer"},
            {"raw_cv": "# Jean\nPython SQL"}
        )

        assert "Madame, Monsieur" in result
        assert mock_llm.invoke.call_count == 1

    def test_generate_letter_markdown_no_api_key(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            generate_letter_markdown,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        monkeypatch.setattr(score_engine, "GENERATION_LLM", None)

        with pytest.raises(LetterGenerationError, match="OPENROUTER_API_KEY"):
            generate_letter_markdown({"title": "Dev"}, {"raw_cv": "# Jean"})

    def test_generate_letter_markdown_empty_response(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            generate_letter_markdown,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = SimpleNamespace(content="   ")
        monkeypatch.setattr(score_engine, "GENERATION_LLM", mock_llm)

        with pytest.raises(LetterGenerationError, match="vide"):
            generate_letter_markdown({"title": "Dev"}, {"raw_cv": "# Jean"})

    def test_generate_letter_markdown_api_error(self, monkeypatch):
        from src.core.scoring.letter_generator_llm import (
            generate_letter_markdown,
            LetterGenerationError,
        )
        from src.core.scoring import score_engine

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API down")
        monkeypatch.setattr(score_engine, "GENERATION_LLM", mock_llm)

        with pytest.raises(LetterGenerationError, match="erreur API"):
            generate_letter_markdown({"title": "Dev"}, {"raw_cv": "# Jean"})
