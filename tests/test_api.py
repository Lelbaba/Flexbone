from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_extract_success(client: TestClient, jpeg: bytes) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", jpeg, "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["text"] == "Hello world"
    assert response.json()["confidence"] == 0.95
    assert response.json()["success"] is True
    assert response.json()["processing_time_ms"] >= 0
    assert "app;dur=" in response.headers["server-timing"]


def test_missing_file(client: TestClient) -> None:
    response = client.post("/extract-text", files={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"


def test_empty_file(client: TestClient) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", b"", "image/jpeg")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_upload"


def test_png_renamed_to_jpeg(client: TestClient) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", b"\x89PNG\r\n", "image/jpeg")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_image_format"


def test_corrupt_jpeg(client: TestClient) -> None:
    response = client.post("/extract-text", files={"image": ("x.jpg", b"\xff\xd8\xffbroken", "image/jpeg")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_image"


def test_file_limit(client: TestClient) -> None:
    payload = b"\xff\xd8\xff" + b"x" * (10 * 1024 * 1024)
    response = client.post("/extract-text", files={"image": ("x.jpg", payload, "image/jpeg")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"


def test_openapi_documents_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/extract-text" in schema["paths"]
    assert "415" in schema["paths"]["/extract-text"]["post"]["responses"]

