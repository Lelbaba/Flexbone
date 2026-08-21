import time

from fastapi import UploadFile

from .domain import OCRProvider, SuccessResponse
from .validation import read_validated_jpeg


class ExtractTextService:
    def __init__(self, provider: OCRProvider, max_image_bytes: int) -> None:
        self._provider = provider
        self._max_image_bytes = max_image_bytes

    async def execute(self, upload: UploadFile) -> tuple[SuccessResponse, int]:
        started = time.perf_counter()
        image = await read_validated_jpeg(upload, self._max_image_bytes)
        result = await self._provider.extract(image)
        elapsed = max(0, round((time.perf_counter() - started) * 1000))
        return (
            SuccessResponse(
                text=result.text,
                confidence=result.confidence,
                processing_time_ms=elapsed,
            ),
            result.retry_count,
        )
