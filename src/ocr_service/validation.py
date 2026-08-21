import io

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .errors import CorruptImage, EmptyUpload, ImageTooLarge, UnsupportedImageFormat

JPEG_MAGIC = b"\xff\xd8\xff"


async def read_validated_jpeg(upload: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    try:
        while chunk := await upload.read(min(64 * 1024, max_bytes + 1 - len(data))):
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ImageTooLarge
        raw = bytes(data)
        if not raw:
            raise EmptyUpload
        if not raw.startswith(JPEG_MAGIC):
            raise UnsupportedImageFormat
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "JPEG":
                    raise UnsupportedImageFormat
                image.verify()
        except UnsupportedImageFormat:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CorruptImage from exc
        return raw
    finally:
        await upload.close()
