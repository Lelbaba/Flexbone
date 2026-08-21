from ocr_service.service import normalize_text


def test_normalize_text_preserves_lines_and_normalizes_unicode() -> None:
    assert normalize_text("  Cafe\u0301 \t text\r\nnext   line \r\n") == "Café text\nnext line"


def test_normalize_empty_text() -> None:
    assert normalize_text("") == ""
