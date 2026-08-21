import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_service.app import create_app
from ocr_service.domain import OCRResult


class FakeProvider:
    async def extract(self, image: bytes) -> OCRResult:
        return OCRResult("Hello world", 0.95)

    async def close(self) -> None:
        pass


@pytest.fixture
def jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(provider_factory=FakeProvider)) as value:
        yield value
