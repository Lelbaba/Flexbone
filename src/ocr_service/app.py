import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.cloud import vision_v1
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .domain import ErrorDetail, ErrorResponse, HealthResponse, OCRProvider, SuccessResponse
from .errors import AppError, MalformedRequest
from .middleware import RequestBodyLimitMiddleware, RequestContextMiddleware
from .service import ExtractTextService
from .vision import GoogleVisionProvider

logger = logging.getLogger("ocr_service")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _error(error: AppError, started: float) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=error.code, message=error.message),
        processing_time_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump())


def create_app(
    provider_factory: Callable[[], OCRProvider] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        provider = (
            provider_factory()
            if provider_factory
            else GoogleVisionProvider(
                vision_v1.ImageAnnotatorAsyncClient(),
                timeout=config.vision_timeout_seconds,
                max_retries=config.vision_max_retries,
            )
        )
        app.state.provider = provider
        app.state.extract_service = ExtractTextService(provider, config.max_image_bytes)
        yield
        await provider.close()

    app = FastAPI(
        title="Flexbone OCR API",
        version="1.0.0",
        description="Extract text from JPEG images without retaining uploads or results.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=config.max_request_bytes)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(json.dumps({"event": "request_failed", "error_class": exc.code}))
        return _error(exc, getattr(request.state, "started", time.perf_counter()))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(MalformedRequest(), getattr(request.state, "started", time.perf_counter()))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code in {400, 404, 405}:
            return _error(
                MalformedRequest(), getattr(request.state, "started", time.perf_counter())
            )
        return _error(AppError(), getattr(request.state, "started", time.perf_counter()))

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(json.dumps({"event": "request_failed", "error_class": type(exc).__name__}))
        return _error(AppError(), getattr(request.state, "started", time.perf_counter()))

    @app.get("/healthz", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/extract-text",
        response_model=SuccessResponse,
        responses={code: {"model": ErrorResponse} for code in (400, 413, 415, 422, 500, 503, 504)},
    )
    async def extract_text(
        request: Request, image: Annotated[UploadFile, File(description="JPEG image, up to 10 MiB")]
    ) -> SuccessResponse:
        request.state.started = time.perf_counter()
        uploads = (await request.form()).getlist("image")
        if len(uploads) != 1:
            for upload in uploads:
                if isinstance(upload, UploadFile):
                    await upload.close()
            raise MalformedRequest
        service = cast(ExtractTextService, request.app.state.extract_service)
        response, retry_count = await service.execute(image)
        logger.info(
            json.dumps(
                {
                    "event": "ocr_complete",
                    "status": 200,
                    "latency_ms": response.processing_time_ms,
                    "retry_count": retry_count,
                }
            )
        )
        return response

    return app


app = create_app()
