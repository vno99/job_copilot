from src.core.scoring.score_engine import normalize_text


def test_normalize_text():
    assert normalize_text("  HELLO world  ") == "hello world"
    assert normalize_text(None) == ""
    assert normalize_text("") == ""
