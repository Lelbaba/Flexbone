import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BASE_URL = os.getenv("OCR_INTEGRATION_BASE_URL")
ROOT = Path(__file__).parent.parent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BASE_URL, reason="OCR_INTEGRATION_BASE_URL is not set"),
]


@pytest.fixture(scope="module")
def live_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        yield client


def upload(client: httpx.Client, path: str) -> httpx.Response:
    image = ROOT / path
    with image.open("rb") as content:
        return client.post(
            "/extract-text",
            files={"image": (image.name, content, "image/jpeg")},
        )


def test_live_health(live_client: httpx.Client) -> None:
    response = live_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("samples/normal.jpg", "flexbone"),
        ("samples/rotated.jpg", "rotated"),
        ("samples/low-contrast.jpg", "contrast"),
        ("test-images/english-handwriting.jpg", "austin"),
        ("test-images/degraded/english-heavy-blur.jpg", "zshc"),
        ("test-images/degraded/english-rotated-17deg.jpg", "zshc"),
    ],
)
def test_live_ocr_quality(live_client: httpx.Client, path: str, expected: str) -> None:
    response = upload(live_client, path)
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert expected in body["text"].lower()
    assert 0 < body["confidence"] <= 1


def test_live_blank_image(live_client: httpx.Client) -> None:
    response = upload(live_client, "samples/blank.jpg")
    assert response.status_code == 200
    assert response.json()["text"] == ""
    assert response.json()["confidence"] == 0


def test_live_rejects_unsupported_format(live_client: httpx.Client) -> None:
    image = ROOT / "samples/unsupported.bmp"
    with image.open("rb") as content:
        response = live_client.post(
            "/extract-text", files={"image": (image.name, content, "image/bmp")}
        )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_live_http_errors_are_specific(live_client: httpx.Client) -> None:
    missing = live_client.get("/does-not-exist")
    wrong_method = live_client.get("/extract-text")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    assert (wrong_method.status_code, wrong_method.json()["error"]["code"]) == (
        405,
        "method_not_allowed",
    )
