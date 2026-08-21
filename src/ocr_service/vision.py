import asyncio
import random
from collections.abc import Awaitable, Callable

from google.api_core import exceptions as google_exceptions
from google.cloud import vision_v1

from .models import AppError


def confidence_from_annotation(annotation: object) -> float:
    total = 0.0
    symbols = 0
    pages = getattr(annotation, "pages", ())
    for page in pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    count = len(word.symbols)
                    if count and word.confidence is not None:
                        total += float(word.confidence) * count
                        symbols += count
    return max(0.0, min(1.0, total / symbols)) if symbols else 0.0


async def extract_text(
    client: vision_v1.ImageAnnotatorAsyncClient,
    image: bytes,
    *,
    deadline_seconds: float = 20.0,
    max_retries: int = 2,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[str, float, int]:
    request = vision_v1.AnnotateImageRequest(
        image=vision_v1.Image(content=image),
        features=[vision_v1.Feature(type_=vision_v1.Feature.Type.DOCUMENT_TEXT_DETECTION)],
    )
    for attempt in range(max_retries + 1):
        try:
            batch = await client.batch_annotate_images(requests=[request], timeout=deadline_seconds)
            response = batch.responses[0]
            if response.error.message:
                raise AppError("ocr_unavailable")
            annotation = response.full_text_annotation
            text = annotation.text or ""
            confidence = confidence_from_annotation(annotation) if text else 0.0
            return text, confidence, attempt
        except google_exceptions.DeadlineExceeded as exc:
            if attempt == max_retries:
                raise AppError("ocr_deadline_exceeded") from exc
        except (
            google_exceptions.ServiceUnavailable,
            google_exceptions.InternalServerError,
        ) as exc:
            if attempt == max_retries:
                raise AppError("ocr_unavailable") from exc
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as exc:
            raise AppError("ocr_unavailable") from exc
        except google_exceptions.GoogleAPICallError as exc:
            raise AppError("ocr_unavailable") from exc
        delay = min(2.0, 0.25 * (2**attempt)) + random.uniform(0, 0.1)
        await sleep(delay)
    raise AppError("ocr_unavailable")
