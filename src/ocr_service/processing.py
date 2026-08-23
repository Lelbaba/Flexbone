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
_ValidatedBatchItem = tuple[int, ValidatedImage, float]


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
    try:
        raw = await _read_upload_bytes(upload, settings.max_image_bytes)
        metadata = await asyncio.to_thread(inspect_image, raw, settings.max_image_pixels)

        return ValidatedImage(raw, metadata)
    finally:
        await upload.close()


async def _read_upload_bytes(upload: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := await upload.read(min(64 * 1024, max_bytes + 1 - len(data))):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise AppError("image_too_large")

    if not data:
        raise AppError("empty_upload")
    return bytes(data)


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
    await _validate_batch(uploads, settings)
    deadline = asyncio.get_running_loop().time() + settings.batch_timeout_seconds
    results, validated, measured_bytes = await _validate_uploads(uploads, settings, deadline)

    if measured_bytes > settings.max_batch_image_bytes:
        raise AppError("batch_too_large")

    retry_count = await _process_batch_images(
        validated,
        results,
        ocr,
        settings,
        deadline,
        include_metadata=include_metadata,
        normalize=normalize,
    )

    return (
        BatchResponse(
            results=[item for item in results if item is not None],
            processing_time_ms=elapsed_ms(started),
        ),
        retry_count,
        measured_bytes,
        sorted({image.metadata.format for _, image, _ in validated}),
    )


async def _validate_batch(uploads: list[UploadFile], settings: Settings) -> None:
    error_code: str | None = None
    if not 1 <= len(uploads) <= settings.max_batch_images:
        error_code = "invalid_batch"
    elif _known_batch_size(uploads) > settings.max_batch_image_bytes:
        error_code = "batch_too_large"

    if error_code is None:
        return

    await close_uploads(uploads)
    raise AppError(error_code)


def _known_batch_size(uploads: list[UploadFile]) -> int:
    sizes = [upload.size for upload in uploads]
    if any(size is None for size in sizes):
        return 0

    return sum(size for size in sizes if size is not None)


async def _validate_uploads(
    uploads: list[UploadFile],
    settings: Settings,
    deadline: float,
) -> tuple[list[BatchItem | None], list[_ValidatedBatchItem], int]:
    results: list[BatchItem | None] = [None] * len(uploads)
    validated: list[_ValidatedBatchItem] = []

    try:
        for index, upload in enumerate(uploads):
            item_started = time.perf_counter()
            item = await _validate_upload(upload, settings, deadline, index, item_started)
            if isinstance(item, BatchItem):
                results[index] = item
                continue

            validated.append((index, item, item_started))
    finally:
        await close_uploads(uploads)

    measured_bytes = sum(image.metadata.byte_size for _, image, _ in validated)
    return results, validated, measured_bytes


async def _validate_upload(
    upload: UploadFile,
    settings: Settings,
    deadline: float,
    index: int,
    started: float,
) -> ValidatedImage | BatchItem:
    try:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await read_image(upload, settings)

    except AppError as exc:
        return error_item(index, exc, started)

    except TimeoutError:
        return _deadline_error_item(index, started)


async def _process_batch_images(
    validated: list[_ValidatedBatchItem],
    results: list[BatchItem | None],
    ocr: OCRFunction,
    settings: Settings,
    deadline: float,
    *,
    include_metadata: bool,
    normalize: bool,
) -> int:
    semaphore = asyncio.Semaphore(settings.batch_max_concurrency)
    tasks = [
        asyncio.create_task(
            _process_batch_image(
                item,
                results,
                ocr,
                semaphore,
                include_metadata=include_metadata,
                normalize=normalize,
            )
        )
        for item in validated
    ]

    try:
        async with asyncio.timeout(max(0, deadline - asyncio.get_running_loop().time())):
            retry_counts = await asyncio.gather(*tasks)
        return sum(retry_counts)

    except TimeoutError:
        await _cancel_tasks(tasks)
        _mark_unfinished_as_timed_out(validated, results)
        return sum(task.result() for task in tasks if task.done() and not task.cancelled())


async def _process_batch_image(
    item: _ValidatedBatchItem,
    results: list[BatchItem | None],
    ocr: OCRFunction,
    semaphore: asyncio.Semaphore,
    *,
    include_metadata: bool,
    normalize: bool,
) -> int:
    index, image, started = item
    async with semaphore:
        try:
            response, retries = await process_image(
                image,
                ocr,
                include_metadata=include_metadata,
                normalize=normalize,
                started=started,
            )
            results[index] = BatchItem(index=index, status_code=200, **response.model_dump())
            return retries

        except AppError as exc:
            results[index] = error_item(index, exc, started)
            return 0


async def _cancel_tasks(tasks: list[asyncio.Task[int]]) -> None:
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)


def _mark_unfinished_as_timed_out(
    validated: list[_ValidatedBatchItem], results: list[BatchItem | None]
) -> None:
    for index, _, started in validated:
        if results[index] is None:
            results[index] = _deadline_error_item(index, started)


def _deadline_error_item(index: int, started: float) -> BatchItem:
    return error_item(index, AppError("ocr_deadline_exceeded"), started)


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
