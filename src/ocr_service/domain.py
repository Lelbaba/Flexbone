from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float
    retry_count: int = 0


class OCRProvider(Protocol):
    async def extract(self, image: bytes) -> OCRResult: ...

    async def close(self) -> None: ...


class SuccessResponse(BaseModel):
    success: bool = True
    text: str
    confidence: float = Field(ge=0, le=1)
    processing_time_ms: int = Field(ge=0)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    processing_time_ms: int = Field(ge=0)


class HealthResponse(BaseModel):
    status: str = "ok"

