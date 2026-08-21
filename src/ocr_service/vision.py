import asyncio
import random
from collections.abc import Callable

from google.api_core import exceptions as google_exceptions
from google.cloud import vision_v1

from .domain import OCRResult
from .errors import OCRDeadlineExceeded, OCRUnavailable


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


class GoogleVisionProvider:
    def __init__(
        self,
        client: vision_v1.ImageAnnotatorAsyncClient,
        timeout: float = 20.0,
        max_retries: int = 2,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep

    async def extract(self, image: bytes) -> OCRResult:
        request = vision_v1.AnnotateImageRequest(
            image=vision_v1.Image(content=image),
            features=[vision_v1.Feature(type_=vision_v1.Feature.Type.DOCUMENT_TEXT_DETECTION)],
        )
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.annotate_image(request=request, timeout=self._timeout)
                if response.error.message:
                    raise OCRUnavailable
                annotation = response.full_text_annotation
                text = annotation.text or ""
                confidence = confidence_from_annotation(annotation) if text else 0.0
                return OCRResult(text=text, confidence=confidence, retry_count=attempt)
            except google_exceptions.DeadlineExceeded as exc:
                if attempt == self._max_retries:
                    raise OCRDeadlineExceeded from exc
            except (google_exceptions.ServiceUnavailable, google_exceptions.InternalServerError) as exc:
                if attempt == self._max_retries:
                    raise OCRUnavailable from exc
            except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as exc:
                raise OCRUnavailable from exc
            delay = min(2.0, 0.25 * (2**attempt)) + random.uniform(0, 0.1)
            if self._sleep is None:
                await asyncio.sleep(delay)
            else:
                result = self._sleep(delay)
                if hasattr(result, "__await__"):
                    await result  # type: ignore[misc]
        raise OCRUnavailable

    async def close(self) -> None:
        await self._client.close()

