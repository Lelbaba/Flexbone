import io

import pytest
from fastapi import UploadFile

from ocr_service.errors import ImageDimensionsTooLarge, ImageTooLarge
from ocr_service.validation import read_validated_image


@pytest.mark.asyncio
async def test_exact_boundary_is_read_before_validation() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 7))
    with pytest.raises(Exception) as caught:
        await read_validated_image(upload, 10, 1_000)
    assert not isinstance(caught.value, ImageTooLarge)


@pytest.mark.asyncio
async def test_first_byte_over_limit() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 8))
    with pytest.raises(ImageTooLarge):
        await read_validated_image(upload, 10, 1_000)
    assert upload.file.closed


@pytest.mark.asyncio
async def test_decoded_dimension_limit() -> None:
    output = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (11, 10)).save(output, "PNG")
    upload = UploadFile(filename="large.png", file=io.BytesIO(output.getvalue()))
    with pytest.raises(ImageDimensionsTooLarge):
        await read_validated_image(upload, 1_000, 100)
