import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_service.app import create_app


async def fake_ocr(image: bytes) -> tuple[str, float, int]:
    return "Hello world", 0.95, 0


@pytest.fixture
def jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(ocr=fake_ocr)) as value:
        yield value
