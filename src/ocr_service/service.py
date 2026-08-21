import re
import time
import unicodedata

from fastapi import UploadFile

from .domain import OCRProvider, SuccessResponse
from .validation import read_validated_jpeg


class ExtractTextService:
    def __init__(self, provider: OCRProvider, max_image_bytes: int) -> None:
        self._provider = provider
        self._max_image_bytes = max_image_bytes

    async def execute(
        self, upload: UploadFile, *, include_metadata: bool = False, normalize: bool = False
    ) -> tuple[SuccessResponse, int]:
        started = time.perf_counter()
        image = await read_validated_jpeg(upload, self._max_image_bytes)
        result = await self._provider.extract(image.content)
        elapsed = max(0, round((time.perf_counter() - started) * 1000))
        return (
            SuccessResponse(
                text=result.text,
                confidence=result.confidence,
                processing_time_ms=elapsed,
                normalized_text=normalize_text(result.text) if normalize else None,
                metadata=image.metadata if include_metadata else None,
            ),
            result.retry_count,
        )


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()
