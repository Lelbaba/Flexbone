import io

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .domain import ImageMetadata, ValidatedImage
from .errors import (
    CorruptImage,
    EmptyUpload,
    ImageDimensionsTooLarge,
    ImageTooLarge,
    UnsupportedImageFormat,
)

SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF"}


async def read_validated_image(
    upload: UploadFile, max_bytes: int, max_pixels: int
) -> ValidatedImage:
    data = bytearray()
    try:
        while chunk := await upload.read(min(64 * 1024, max_bytes + 1 - len(data))):
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ImageTooLarge
        raw = bytes(data)
        if not raw:
            raise EmptyUpload
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in SUPPORTED_FORMATS:
                    raise UnsupportedImageFormat
                if image.width * image.height > max_pixels:
                    raise ImageDimensionsTooLarge
                metadata = ImageMetadata(
                    width=image.width,
                    height=image.height,
                    byte_size=len(raw),
                    color_mode=image.mode,
                    format=image.format,
                )
                image.verify()
        except (UnsupportedImageFormat, ImageDimensionsTooLarge):
            raise
        except Image.DecompressionBombError as exc:
            raise ImageDimensionsTooLarge from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CorruptImage from exc
        return ValidatedImage(content=raw, metadata=metadata)
    finally:
        await upload.close()
