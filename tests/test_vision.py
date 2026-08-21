from types import SimpleNamespace

import pytest

from ocr_service.vision import GoogleVisionProvider, confidence_from_annotation


def test_symbol_weighted_confidence() -> None:
    words = [
        SimpleNamespace(confidence=1.0, symbols=[1]),
        SimpleNamespace(confidence=0.5, symbols=[1, 2, 3]),
    ]
    annotation = SimpleNamespace(
        pages=[SimpleNamespace(blocks=[SimpleNamespace(paragraphs=[SimpleNamespace(words=words)])])]
    )
    assert confidence_from_annotation(annotation) == 0.625


def test_missing_confidence_is_zero() -> None:
    assert confidence_from_annotation(SimpleNamespace(pages=[])) == 0.0


class FakeVisionClient:
    def __init__(self, text: str) -> None:
        annotation = SimpleNamespace(text=text, pages=[])
        response = SimpleNamespace(
            error=SimpleNamespace(message=""), full_text_annotation=annotation
        )
        self.batch = SimpleNamespace(responses=[response])
        self.transport = self
        self.closed = False

    async def batch_annotate_images(self, **kwargs: object) -> object:
        return self.batch

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "confidence"), [("Detected", 0.0), ("", 0.0)])
async def test_provider_maps_vision_response(text: str, confidence: float) -> None:
    client = FakeVisionClient(text)
    provider = GoogleVisionProvider(client)  # type: ignore[arg-type]
    result = await provider.extract(b"jpeg")
    assert (result.text, result.confidence, result.retry_count) == (text, confidence, 0)
    await provider.close()
    assert client.closed
