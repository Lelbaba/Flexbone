from types import SimpleNamespace

import pytest
from google.api_core import exceptions as google_exceptions

from ocr_service.models import AppError
from ocr_service.vision import confidence_from_annotation, extract_text


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
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def batch_annotate_images(self, **kwargs: object) -> object:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def vision_batch(text: str = "Detected", error: str = "") -> object:
    annotation = SimpleNamespace(text=text, pages=[])
    response = SimpleNamespace(
        error=SimpleNamespace(message=error), full_text_annotation=annotation
    )
    return SimpleNamespace(responses=[response])


async def no_sleep(delay: float) -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Detected", ""])
async def test_extract_text_maps_vision_response(text: str) -> None:
    result = await extract_text(
        FakeVisionClient([vision_batch(text)]),  # type: ignore[arg-type]
        b"jpeg",
    )
    assert result == (text, 0.0, 0)


@pytest.mark.asyncio
async def test_transient_failure_is_retried() -> None:
    client = FakeVisionClient([google_exceptions.ServiceUnavailable("down"), vision_batch()])
    result = await extract_text(  # type: ignore[arg-type]
        client, b"jpeg", max_retries=2, sleep=no_sleep
    )
    assert result == ("Detected", 0.0, 1)
    assert client.calls == 2


@pytest.mark.asyncio
async def test_deadline_after_retries_maps_to_504() -> None:
    client = FakeVisionClient([google_exceptions.DeadlineExceeded("slow")] * 3)
    with pytest.raises(AppError) as caught:
        await extract_text(  # type: ignore[arg-type]
            client, b"jpeg", max_retries=2, sleep=no_sleep
        )
    assert caught.value.code == "ocr_deadline_exceeded"
    assert client.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        google_exceptions.ResourceExhausted("quota"),
        google_exceptions.InvalidArgument("bad request"),
    ],
)
async def test_non_retryable_failures_are_not_retried(failure: Exception) -> None:
    client = FakeVisionClient([failure])
    with pytest.raises(AppError) as caught:
        await extract_text(  # type: ignore[arg-type]
            client, b"jpeg", max_retries=2, sleep=no_sleep
        )
    assert caught.value.code == "ocr_unavailable"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_error_in_vision_response_maps_to_unavailable() -> None:
    with pytest.raises(AppError) as caught:
        await extract_text(  # type: ignore[arg-type]
            FakeVisionClient([vision_batch(error="failed")]), b"jpeg"
        )
    assert caught.value.code == "ocr_unavailable"
