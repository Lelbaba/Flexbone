from types import SimpleNamespace

from ocr_service.vision import confidence_from_annotation


def test_symbol_weighted_confidence() -> None:
    words = [
        SimpleNamespace(confidence=1.0, symbols=[1]),
        SimpleNamespace(confidence=0.5, symbols=[1, 2, 3]),
    ]
    annotation = SimpleNamespace(pages=[SimpleNamespace(blocks=[SimpleNamespace(
        paragraphs=[SimpleNamespace(words=words)]
    )])])
    assert confidence_from_annotation(annotation) == 0.625


def test_missing_confidence_is_zero() -> None:
    assert confidence_from_annotation(SimpleNamespace(pages=[])) == 0.0

