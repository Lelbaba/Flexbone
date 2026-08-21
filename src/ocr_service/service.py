import asyncio
import re
import time
import unicodedata

from fastapi import UploadFile

from .domain import (
    BatchErrorItem,
    BatchResponse,
    BatchSuccessItem,
    ErrorDetail,
    OCRProvider,
    SuccessResponse,
    ValidatedImage,
)
from .errors import AppError, BatchTooLarge, InvalidBatch, OCRDeadlineExceeded
from .validation import read_validated_image


class ExtractTextService:
    def __init__(self, provider: OCRProvider, max_image_bytes: int, max_image_pixels: int) -> None:
        self._provider = provider
        self._max_image_bytes = max_image_bytes
        self._max_image_pixels = max_image_pixels

    async def execute(
        self, upload: UploadFile, *, include_metadata: bool = False, normalize: bool = False
    ) -> tuple[SuccessResponse, int]:
        started = time.perf_counter()
        image = await read_validated_image(upload, self._max_image_bytes, self._max_image_pixels)
        return await self.execute_validated(
            image,
            include_metadata=include_metadata,
            normalize=normalize,
            started=started,
        )

    async def execute_validated(
        self,
        image: ValidatedImage,
        *,
        include_metadata: bool = False,
        normalize: bool = False,
        started: float | None = None,
    ) -> tuple[SuccessResponse, int]:
        started = started if started is not None else time.perf_counter()
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


class ExtractBatchService:
    def __init__(
        self,
        extract_service: ExtractTextService,
        max_image_bytes: int,
        max_image_pixels: int,
        max_images: int,
        max_combined_bytes: int,
        max_concurrency: int,
        timeout_seconds: float,
    ) -> None:
        self._extract_service = extract_service
        self._max_image_bytes = max_image_bytes
        self._max_image_pixels = max_image_pixels
        self._max_images = max_images
        self._max_combined_bytes = max_combined_bytes
        self._max_concurrency = max_concurrency
        self._timeout_seconds = timeout_seconds

    async def execute(
        self,
        uploads: list[UploadFile],
        *,
        include_metadata: bool = False,
        normalize: bool = False,
    ) -> tuple[BatchResponse, int]:
        started = time.perf_counter()
        if not 1 <= len(uploads) <= self._max_images:
            await self._close_all(uploads)
            raise InvalidBatch

        known_sizes = [upload.size for upload in uploads]
        known_total = sum(size for size in known_sizes if size is not None)
        if all(size is not None for size in known_sizes) and known_total > self._max_combined_bytes:
            await self._close_all(uploads)
            raise BatchTooLarge

        results: list[BatchSuccessItem | BatchErrorItem | None] = [None] * len(uploads)
        validated: list[tuple[int, ValidatedImage, float]] = []
        measured_bytes = 0
        try:
            for index, upload in enumerate(uploads):
                item_started = time.perf_counter()
                try:
                    image = await read_validated_image(
                        upload, self._max_image_bytes, self._max_image_pixels
                    )
                    measured_bytes += image.metadata.byte_size
                    validated.append((index, image, item_started))
                except AppError as exc:
                    results[index] = self._error_item(index, exc, item_started)
        finally:
            await self._close_all(uploads)

        if measured_bytes > self._max_combined_bytes:
            raise BatchTooLarge

        semaphore = asyncio.Semaphore(self._max_concurrency)
        retry_count = 0

        async def process(index: int, image: ValidatedImage, item_started: float) -> None:
            nonlocal retry_count
            async with semaphore:
                try:
                    response, retries = await self._extract_service.execute_validated(
                        image,
                        include_metadata=include_metadata,
                        normalize=normalize,
                        started=item_started,
                    )
                    retry_count += retries
                    results[index] = BatchSuccessItem(
                        index=index, status_code=200, **response.model_dump()
                    )
                except AppError as exc:
                    results[index] = self._error_item(index, exc, item_started)

        tasks = [asyncio.create_task(process(*item)) for item in validated]
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await asyncio.gather(*tasks)
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for index, _, item_started in validated:
                if results[index] is None:
                    results[index] = self._error_item(index, OCRDeadlineExceeded(), item_started)

        elapsed = max(0, round((time.perf_counter() - started) * 1000))
        return (
            BatchResponse(
                results=[item for item in results if item is not None],
                processing_time_ms=elapsed,
            ),
            retry_count,
        )

    @staticmethod
    def _error_item(index: int, error: AppError, started: float) -> BatchErrorItem:
        elapsed = max(0, round((time.perf_counter() - started) * 1000))
        return BatchErrorItem(
            index=index,
            status_code=error.status_code,
            error=ErrorDetail(code=error.code, message=error.message),
            processing_time_ms=elapsed,
        )

    @staticmethod
    async def _close_all(uploads: list[UploadFile]) -> None:
        await asyncio.gather(*(upload.close() for upload in uploads))


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()
