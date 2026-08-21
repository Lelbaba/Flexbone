import io

import pytest
from fastapi import UploadFile

from ocr_service.config import Settings
from ocr_service.models import AppError
from ocr_service.processing import read_image


@pytest.mark.asyncio
async def test_exact_boundary_is_read_before_validation() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 7))
    with pytest.raises(Exception) as caught:
        await read_image(upload, Settings(max_image_bytes=10, max_image_pixels=1_000))
    assert not (isinstance(caught.value, AppError) and caught.value.code == "image_too_large")


@pytest.mark.asyncio
async def test_first_byte_over_limit() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 8))
    with pytest.raises(AppError) as caught:
        await read_image(upload, Settings(max_image_bytes=10, max_image_pixels=1_000))
    assert caught.value.code == "image_too_large"
    assert upload.file.closed


@pytest.mark.asyncio
async def test_decoded_dimension_limit() -> None:
    output = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (11, 10)).save(output, "PNG")
    upload = UploadFile(filename="large.png", file=io.BytesIO(output.getvalue()))
    with pytest.raises(AppError) as caught:
        await read_image(upload, Settings(max_image_bytes=1_000, max_image_pixels=100))
    assert caught.value.code == "image_dimensions_too_large"
