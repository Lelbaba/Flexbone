import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated, cast

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from google.cloud import vision_v1
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .middleware import RequestBodyLimitMiddleware, RequestContextMiddleware
from .models import (
    AppError,
    BatchResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    SuccessResponse,
)
from .processing import OCRFunction, close_uploads, extract_batch, extract_one
from .vision import extract_text as extract_with_vision

logger = logging.getLogger("ocr_service")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _error(error: AppError, started: float) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=error.code, message=error.message),
        processing_time_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump())


def _log_failure(request: Request, error: AppError) -> None:
    logger.warning(
        json.dumps(
            {
                "event": "request_failed",
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": error.status_code,
                "error_class": error.code,
            }
        )
    )


def create_app(ocr: OCRFunction | None = None, settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if ocr is not None:
            app.state.ocr = ocr
            yield
            return

        client = vision_v1.ImageAnnotatorAsyncClient()
        app.state.ocr = partial(
            extract_with_vision,
            client,
            deadline_seconds=config.vision_timeout_seconds,
            max_retries=config.vision_max_retries,
        )

        yield
        await client.transport.close()  # type: ignore[no-untyped-call]

    app = FastAPI(
        title="Flexbone OCR API",
        version="1.0.0",
        description=(
            "Extract text from JPEG, PNG, and GIF images without retaining uploads or results."
        ),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=config.max_request_bytes,
        path_limits={"/extract-text/batch": config.max_batch_request_bytes},
    )

    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        expose_headers=["Server-Timing", "X-Request-ID"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        _log_failure(request, exc)

        return _error(exc, request.state.started)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        error = AppError(
            "invalid_batch" if request.url.path == "/extract-text/batch" else "malformed_request"
        )
        _log_failure(request, error)

        return _error(error, request.state.started)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {400: "malformed_request", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "internal_error"
        )
        error = AppError(code)
        _log_failure(request, error)

        return _error(error, request.state.started)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            json.dumps(
                {
                    "event": "request_failed",
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "error_class": type(exc).__name__,
                }
            )
        )

        return _error(AppError("internal_error"), request.state.started)

    @app.get("/health", response_model=HealthResponse)
    @app.get("/healthz", response_model=HealthResponse, include_in_schema=False)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/docs", include_in_schema=False)
    @app.get("/docs/", include_in_schema=False)
    async def docs() -> RedirectResponse:
        return RedirectResponse(config.public_docs_url)

    @app.post(
        "/extract-text",
        response_model=SuccessResponse,
        response_model_exclude_none=True,
        responses={code: {"model": ErrorResponse} for code in (400, 413, 415, 422, 500, 503, 504)},
    )
    async def extract_text(
        request: Request,
        image: Annotated[UploadFile, File(description="JPEG, PNG, or GIF image, up to 10 MiB")],
        include_metadata: Annotated[bool, Query(alias="metadata")] = False,
        normalize: bool = False,
    ) -> SuccessResponse:
        uploads = (await request.form()).getlist("image")
        if len(uploads) != 1:
            await close_uploads([item for item in uploads if isinstance(item, UploadFile)])
            raise AppError("malformed_request")

        ocr_function = cast(OCRFunction, request.app.state.ocr)
        response, retry_count, metadata = await extract_one(
            image,
            ocr_function,
            config,
            include_metadata=include_metadata,
            normalize=normalize,
            started=request.state.started,
        )

        logger.info(
            json.dumps(
                {
                    "event": "ocr_complete",
                    "request_id": request.state.request_id,
                    "status": 200,
                    "image_size_bytes": metadata.byte_size,
                    "image_format": metadata.format,
                    "latency_ms": response.processing_time_ms,
                    "retry_count": retry_count,
                }
            )
        )

        return response

    @app.post(
        "/extract-text/batch",
        response_model=BatchResponse,
        response_model_exclude_none=True,
        responses={code: {"model": ErrorResponse} for code in (400, 413, 500)},
    )
    async def extract_text_batch(
        request: Request,
        images: Annotated[
            list[UploadFile], File(description="One to five images, up to 10 MiB each")
        ],
        include_metadata: Annotated[bool, Query(alias="metadata")] = False,
        normalize: bool = False,
    ) -> BatchResponse:
        ocr_function = cast(OCRFunction, request.app.state.ocr)
        response, retry_count, image_bytes, image_formats = await extract_batch(
            images,
            ocr_function,
            config,
            include_metadata=include_metadata,
            normalize=normalize,
            started=request.state.started,
        )

        logger.info(
            json.dumps(
                {
                    "event": "ocr_batch_complete",
                    "request_id": request.state.request_id,
                    "status": 200,
                    "item_count": len(response.results),
                    "success_count": sum(item.success for item in response.results),
                    "image_size_bytes": image_bytes,
                    "image_formats": image_formats,
                    "latency_ms": response.processing_time_ms,
                    "retry_count": retry_count,
                }
            )
        )

        return response

    return app


app = create_app()
