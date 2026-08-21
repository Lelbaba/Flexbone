import asyncio
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_service.app import create_app
from ocr_service.config import Settings


def test_health(client: TestClient) -> None:
    for path in ("/health", "/healthz"):
        response = client.get(path)
        assert response.json() == {"status": "ok"}
        assert response.headers["x-request-id"]


def test_extract_success(client: TestClient, jpeg: bytes) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", jpeg, "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["text"] == "Hello world"
    assert response.json()["confidence"] == 0.95
    assert response.json()["success"] is True
    assert response.json()["processing_time_ms"] >= 0
    assert "metadata" not in response.json()
    assert "normalized_text" not in response.json()
    assert "app;dur=" in response.headers["server-timing"]


def test_opt_in_metadata_and_normalization(client: TestClient, jpeg: bytes) -> None:
    response = client.post(
        "/extract-text?metadata=true&normalize=true",
        files={"image": ("x.jpg", jpeg, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["normalized_text"] == "Hello world"
    assert response.json()["metadata"] == {
        "width": 16,
        "height": 16,
        "byte_size": len(jpeg),
        "color_mode": "RGB",
        "format": "JPEG",
    }


def test_missing_file(client: TestClient) -> None:
    response = client.post("/extract-text", files={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"


def test_duplicate_file(client: TestClient, jpeg: bytes) -> None:
    response = client.post(
        "/extract-text",
        files=[("image", ("a.jpg", jpeg, "image/jpeg")), ("image", ("b.jpg", jpeg, "image/jpeg"))],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"


def test_empty_file(client: TestClient) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", b"", "image/jpeg")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_upload"


def test_unsupported_bmp_renamed_to_jpeg(client: TestClient) -> None:
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, "BMP")
    response = client.post(
        "/extract-text", files={"image": ("x.jpg", output.getvalue(), "image/jpeg")}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_png_is_accepted_regardless_of_declared_type(client: TestClient) -> None:
    output = io.BytesIO()
    Image.new("RGBA", (12, 8), "white").save(output, "PNG")
    response = client.post(
        "/extract-text?metadata=true",
        files={"image": ("renamed.jpg", output.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["format"] == "PNG"
    assert response.json()["metadata"]["color_mode"] == "RGBA"


def test_animated_gif_is_accepted(client: TestClient) -> None:
    output = io.BytesIO()
    frames = [Image.new("RGB", (12, 8), color) for color in ("white", "black")]
    frames[0].save(output, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    response = client.post(
        "/extract-text?metadata=true",
        files={"image": ("animated.gif", output.getvalue(), "image/gif")},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["format"] == "GIF"


def test_corrupt_jpeg(client: TestClient) -> None:
    response = client.post(
        "/extract-text", files={"image": ("x.jpg", b"\xff\xd8\xffbroken", "image/jpeg")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_image"


def test_truncated_png(client: TestClient) -> None:
    response = client.post(
        "/extract-text", files={"image": ("x.png", b"\x89PNG\r\n\x1a\ntruncated", "image/png")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_image"


def test_file_limit(client: TestClient) -> None:
    payload = b"\xff\xd8\xff" + b"x" * (10 * 1024 * 1024)
    response = client.post("/extract-text", files={"image": ("x.jpg", payload, "image/jpeg")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"


def test_request_body_limit_has_context_headers(client: TestClient) -> None:
    response = client.post(
        "/extract-text",
        content=b"x",
        headers={"content-type": "multipart/form-data", "content-length": str(12 * 1024 * 1024)},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert response.headers["x-request-id"]
    assert response.headers["server-timing"]


def test_openapi_documents_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/extract-text" in schema["paths"]
    assert "415" in schema["paths"]["/extract-text"]["post"]["responses"]


def test_docs_redirects_to_public_guide(client: TestClient) -> None:
    response = client.get("/docs", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://ocr.lelbaba.top/api-docs.html"


def test_frontend_origin_is_allowed_by_cors(client: TestClient) -> None:
    response = client.options(
        "/extract-text",
        headers={
            "origin": "https://ocr.lelbaba.top",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://ocr.lelbaba.top"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_unknown_origin_is_not_allowed_by_cors(client: TestClient) -> None:
    response = client.get("/health", headers={"origin": "https://example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_unknown_route_and_wrong_method_have_specific_errors(client: TestClient) -> None:
    missing = client.get("/does-not-exist")
    wrong_method = client.get("/extract-text")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


async def slow_ocr(image: bytes) -> tuple[str, float, int]:
    await asyncio.sleep(1)
    return "late", 0.9, 0


def test_single_request_has_an_application_timeout(jpeg: bytes) -> None:
    settings = Settings(request_timeout_seconds=0.01)
    with TestClient(create_app(ocr=slow_ocr, settings=settings)) as client:
        response = client.post("/extract-text", files={"image": ("x.jpg", jpeg, "image/jpeg")})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ocr_deadline_exceeded"


def test_success_log_contains_safe_request_context(
    client: TestClient, jpeg: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="ocr_service"):
        response = client.post(
            "/extract-text",
            files={"image": ("x.jpg", jpeg, "image/jpeg")},
            headers={"x-request-id": "test-request"},
        )

    record = next(
        json.loads(item.message)
        for item in caplog.records
        if '"event": "ocr_complete"' in item.message
    )
    assert response.status_code == 200
    assert record["request_id"] == "test-request"
    assert record["image_size_bytes"] == len(jpeg)
    assert record["image_format"] == "JPEG"
    assert "text" not in record
