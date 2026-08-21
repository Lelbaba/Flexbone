import io

import pytest
from fastapi import UploadFile

from ocr_service.errors import ImageTooLarge
from ocr_service.validation import read_validated_jpeg


@pytest.mark.asyncio
async def test_exact_boundary_is_read_before_validation() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 7))
    with pytest.raises(Exception) as caught:
        await read_validated_jpeg(upload, 10)
    assert not isinstance(caught.value, ImageTooLarge)


@pytest.mark.asyncio
async def test_first_byte_over_limit() -> None:
    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"\xff\xd8\xff" + b"x" * 8))
    with pytest.raises(ImageTooLarge):
        await read_validated_jpeg(upload, 10)
    assert upload.file.closed
