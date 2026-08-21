import io

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .domain import ImageMetadata, ValidatedImage
from .errors import CorruptImage, EmptyUpload, ImageTooLarge, UnsupportedImageFormat

JPEG_MAGIC = b"\xff\xd8\xff"


async def read_validated_jpeg(upload: UploadFile, max_bytes: int) -> ValidatedImage:
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
                metadata = ImageMetadata(
                    width=image.width,
                    height=image.height,
                    byte_size=len(raw),
                    color_mode=image.mode,
                    format=image.format,
                )
                image.verify()
        except UnsupportedImageFormat:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CorruptImage from exc
        return ValidatedImage(content=raw, metadata=metadata)
    finally:
        await upload.close()
