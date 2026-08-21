import asyncio
import io

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from ocr_service.app import create_app
from ocr_service.config import Settings
from ocr_service.domain import OCRResult
from ocr_service.errors import BatchTooLarge, OCRUnavailable
from ocr_service.service import ExtractBatchService, ExtractTextService


class FakeProvider:
    async def extract(self, image: bytes) -> OCRResult:
        return OCRResult("Hello  world", 0.95)

    async def close(self) -> None:
        pass


def batch_files(images: list[bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("images", (f"image-{index}.jpg", image, "image/jpeg"))
        for index, image in enumerate(images)
    ]


def test_batch_success_preserves_order_and_options(client: TestClient, jpeg: bytes) -> None:
    response = client.post(
        "/extract-text/batch?metadata=true&normalize=true",
        files=batch_files([jpeg, jpeg, jpeg]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["processing_time_ms"] >= 0
    assert [item["index"] for item in body["results"]] == [0, 1, 2]
    assert all(item["status_code"] == 200 for item in body["results"])
    assert all(item["normalized_text"] == "Hello world" for item in body["results"])
    assert all(item["metadata"]["format"] == "JPEG" for item in body["results"])


def test_batch_isolates_invalid_images(client: TestClient, jpeg: bytes) -> None:
    response = client.post(
        "/extract-text/batch",
        files=batch_files([jpeg, b"\xff\xd8\xffbroken", jpeg]),
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["success"] for item in results] == [True, False, True]
    assert results[1]["status_code"] == 422
    assert results[1]["error"]["code"] == "corrupt_image"


def test_batch_requires_one_to_five_images(client: TestClient, jpeg: bytes) -> None:
    missing = client.post("/extract-text/batch", files={})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_batch"

    too_many = client.post("/extract-text/batch", files=batch_files([jpeg] * 6))
    assert too_many.status_code == 400
    assert too_many.json()["error"]["code"] == "invalid_batch"


def test_batch_enforces_individual_image_limit(jpeg: bytes) -> None:
    settings = Settings(max_image_bytes=len(jpeg), max_batch_image_bytes=len(jpeg) * 3)
    with TestClient(create_app(provider_factory=FakeProvider, settings=settings)) as client:
        response = client.post("/extract-text/batch", files=batch_files([jpeg, jpeg + b"x"]))

    assert response.status_code == 200
    assert response.json()["results"][1]["status_code"] == 413
    assert response.json()["results"][1]["error"]["code"] == "image_too_large"


def test_batch_enforces_exact_combined_image_limit(jpeg: bytes) -> None:
    combined_limit = len(jpeg) * 2
    settings = Settings(
        max_image_bytes=len(jpeg) + 1,
        max_batch_image_bytes=combined_limit,
        request_overhead_bytes=4096,
    )
    with TestClient(create_app(provider_factory=FakeProvider, settings=settings)) as client:
        exact = client.post("/extract-text/batch", files=batch_files([jpeg, jpeg]))
        over = client.post("/extract-text/batch", files=batch_files([jpeg, jpeg + b"x"]))

    assert exact.status_code == 200
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "batch_too_large"


@pytest.mark.asyncio
async def test_batch_measures_combined_size_when_upload_size_is_unknown(jpeg: bytes) -> None:
    provider = FakeProvider()
    service = ExtractBatchService(
        extract_service=ExtractTextService(provider, len(jpeg), 1_000_000),
        max_image_bytes=len(jpeg),
        max_image_pixels=1_000_000,
        max_images=5,
        max_combined_bytes=len(jpeg) - 1,
        max_concurrency=2,
        timeout_seconds=1,
    )
    upload = UploadFile(filename="image.jpg", file=io.BytesIO(jpeg))

    with pytest.raises(BatchTooLarge):
        await service.execute([upload])

    assert upload.file.closed


def test_batch_request_body_guard_uses_batch_limit() -> None:
    settings = Settings(max_batch_image_bytes=100, request_overhead_bytes=100)
    with TestClient(create_app(provider_factory=FakeProvider, settings=settings)) as client:
        response = client.post(
            "/extract-text/batch",
            content=b"x",
            headers={
                "content-type": "multipart/form-data",
                "content-length": "201",
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert response.headers["x-request-id"]


class TrackingProvider:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def extract(self, image: bytes) -> OCRResult:
        identifier = image[-1]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep((6 - identifier) * 0.005)
            return OCRResult(str(identifier), 0.9)
        finally:
            self.active -= 1

    async def close(self) -> None:
        pass


def test_batch_limits_provider_concurrency_and_preserves_order(jpeg: bytes) -> None:
    provider = TrackingProvider()
    images = [jpeg + bytes([identifier]) for identifier in range(1, 6)]
    with TestClient(create_app(provider_factory=lambda: provider)) as client:
        response = client.post("/extract-text/batch", files=batch_files(images))

    assert response.status_code == 200
    assert provider.max_active == 2
    assert [item["text"] for item in response.json()["results"]] == ["1", "2", "3", "4", "5"]


class MixedProvider:
    async def extract(self, image: bytes) -> OCRResult:
        if image[-1] == 2:
            raise OCRUnavailable
        return OCRResult(str(image[-1]), 0.9)

    async def close(self) -> None:
        pass


def test_batch_isolates_provider_failures(jpeg: bytes) -> None:
    with TestClient(create_app(provider_factory=MixedProvider)) as client:
        response = client.post(
            "/extract-text/batch", files=batch_files([jpeg + b"\x01", jpeg + b"\x02"])
        )

    results = response.json()["results"]
    assert response.status_code == 200
    assert results[0]["success"] is True
    assert results[1]["status_code"] == 503
    assert results[1]["error"]["code"] == "ocr_unavailable"


class SlowProvider:
    async def extract(self, image: bytes) -> OCRResult:
        await asyncio.sleep(1)
        return OCRResult("late", 0.9)

    async def close(self) -> None:
        pass


def test_batch_timeout_marks_unfinished_items(jpeg: bytes) -> None:
    settings = Settings(batch_timeout_seconds=0.01)
    with TestClient(create_app(provider_factory=SlowProvider, settings=settings)) as client:
        response = client.post("/extract-text/batch", files=batch_files([jpeg] * 3))

    assert response.status_code == 200
    assert [item["status_code"] for item in response.json()["results"]] == [504, 504, 504]
    assert all(
        item["error"]["code"] == "ocr_deadline_exceeded" for item in response.json()["results"]
    )


def test_openapi_documents_batch_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/extract-text/batch"]["post"]

    assert "200" in operation["responses"]
    assert "400" in operation["responses"]
    assert "413" in operation["responses"]
