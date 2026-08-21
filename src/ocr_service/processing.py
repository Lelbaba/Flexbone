import asyncio
import io
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .config import Settings
from .models import (
    AppError,
    BatchItem,
    BatchResponse,
    ErrorDetail,
    ImageMetadata,
    SuccessResponse,
    ValidatedImage,
)

OCRFunction = Callable[[bytes], Awaitable[tuple[str, float, int]]]
SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF"}


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def inspect_image(raw: bytes, max_pixels: int) -> ImageMetadata:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in SUPPORTED_FORMATS:
                raise AppError("unsupported_image_format")
            if image.width * image.height > max_pixels:
                raise AppError("image_dimensions_too_large")
            metadata = ImageMetadata(
                width=image.width,
                height=image.height,
                byte_size=len(raw),
                color_mode=image.mode,
                format=image.format,
            )
            image.verify()
            return metadata
    except AppError:
        raise
    except Image.DecompressionBombError as exc:
        raise AppError("image_dimensions_too_large") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError("corrupt_image") from exc


async def read_image(upload: UploadFile, settings: Settings) -> ValidatedImage:
    data = bytearray()
    try:
        while chunk := await upload.read(min(64 * 1024, settings.max_image_bytes + 1 - len(data))):
            data.extend(chunk)
            if len(data) > settings.max_image_bytes:
                raise AppError("image_too_large")
        raw = bytes(data)
        if not raw:
            raise AppError("empty_upload")
        metadata = await asyncio.to_thread(inspect_image, raw, settings.max_image_pixels)
        return ValidatedImage(raw, metadata)
    finally:
        await upload.close()


async def process_image(
    image: ValidatedImage,
    ocr: OCRFunction,
    *,
    include_metadata: bool,
    normalize: bool,
    started: float,
) -> tuple[SuccessResponse, int]:
    text, confidence, retry_count = await ocr(image.content)
    response = SuccessResponse(
        text=text,
        confidence=confidence,
        processing_time_ms=elapsed_ms(started),
        normalized_text=normalize_text(text) if normalize else None,
        metadata=image.metadata if include_metadata else None,
    )
    return response, retry_count


async def extract_one(
    upload: UploadFile,
    ocr: OCRFunction,
    settings: Settings,
    *,
    include_metadata: bool,
    normalize: bool,
    started: float,
) -> tuple[SuccessResponse, int, ImageMetadata]:
    try:
        async with asyncio.timeout(settings.request_timeout_seconds):
            image = await read_image(upload, settings)
            response, retries = await process_image(
                image,
                ocr,
                include_metadata=include_metadata,
                normalize=normalize,
                started=started,
            )
            return response, retries, image.metadata
    except TimeoutError as exc:
        raise AppError("ocr_deadline_exceeded") from exc


async def extract_batch(
    uploads: list[UploadFile],
    ocr: OCRFunction,
    settings: Settings,
    *,
    include_metadata: bool,
    normalize: bool,
    started: float,
) -> tuple[BatchResponse, int, int, list[str]]:
    if not 1 <= len(uploads) <= settings.max_batch_images:
        await close_uploads(uploads)
        raise AppError("invalid_batch")

    known_sizes = [upload.size for upload in uploads]
    known_total = sum(size for size in known_sizes if size is not None)
    if (
        all(size is not None for size in known_sizes)
        and known_total > settings.max_batch_image_bytes
    ):
        await close_uploads(uploads)
        raise AppError("batch_too_large")

    deadline = asyncio.get_running_loop().time() + settings.batch_timeout_seconds
    results: list[BatchItem | None] = [None] * len(uploads)
    validated: list[tuple[int, ValidatedImage, float]] = []
    measured_bytes = 0

    try:
        for index, upload in enumerate(uploads):
            item_started = time.perf_counter()
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    image = await read_image(upload, settings)
                measured_bytes += image.metadata.byte_size
                validated.append((index, image, item_started))
            except AppError as exc:
                results[index] = error_item(index, exc, item_started)
            except TimeoutError:
                results[index] = error_item(index, AppError("ocr_deadline_exceeded"), item_started)
    finally:
        await close_uploads(uploads)

    if measured_bytes > settings.max_batch_image_bytes:
        raise AppError("batch_too_large")

    semaphore = asyncio.Semaphore(settings.batch_max_concurrency)
    retry_count = 0

    async def process(index: int, image: ValidatedImage, item_started: float) -> None:
        nonlocal retry_count
        async with semaphore:
            try:
                response, retries = await process_image(
                    image,
                    ocr,
                    include_metadata=include_metadata,
                    normalize=normalize,
                    started=item_started,
                )
                retry_count += retries
                results[index] = BatchItem(
                    index=index,
                    status_code=200,
                    **response.model_dump(),
                )
            except AppError as exc:
                results[index] = error_item(index, exc, item_started)

    tasks = [asyncio.create_task(process(*item)) for item in validated]
    remaining = max(0, deadline - asyncio.get_running_loop().time())
    try:
        async with asyncio.timeout(remaining):
            await asyncio.gather(*tasks)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for index, _, item_started in validated:
            if results[index] is None:
                results[index] = error_item(index, AppError("ocr_deadline_exceeded"), item_started)

    return (
        BatchResponse(
            results=[item for item in results if item is not None],
            processing_time_ms=elapsed_ms(started),
        ),
        retry_count,
        measured_bytes,
        sorted({image.metadata.format for _, image, _ in validated}),
    )


def error_item(index: int, error: AppError, started: float) -> BatchItem:
    return BatchItem(
        index=index,
        status_code=error.status_code,
        success=False,
        error=ErrorDetail(code=error.code, message=error.message),
        processing_time_ms=elapsed_ms(started),
    )


async def close_uploads(uploads: list[UploadFile]) -> None:
    await asyncio.gather(*(upload.close() for upload in uploads))


def elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
