from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    width: int
    height: int
    byte_size: int
    color_mode: str
    format: str


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    content: bytes
    metadata: ImageMetadata


class OCRProvider(Protocol):
    async def extract(self, image: bytes) -> OCRResult: ...

    async def close(self) -> None: ...


class SuccessResponse(BaseModel):
    success: bool = True
    text: str
    confidence: float = Field(ge=0, le=1)
    processing_time_ms: int = Field(ge=0)
    normalized_text: str | None = None
    metadata: ImageMetadata | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    processing_time_ms: int = Field(ge=0)


class BatchSuccessItem(SuccessResponse):
    index: int = Field(ge=0)
    status_code: int = 200


class BatchErrorItem(ErrorResponse):
    index: int = Field(ge=0)
    status_code: int = Field(ge=400, le=599)


class BatchResponse(BaseModel):
    success: bool = True
    results: list[BatchSuccessItem | BatchErrorItem]
    processing_time_ms: int = Field(ge=0)


class HealthResponse(BaseModel):
    status: str = "ok"
