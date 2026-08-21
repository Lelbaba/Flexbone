from dataclasses import dataclass

from pydantic import BaseModel, Field

ERRORS: dict[str, tuple[int, str]] = {
    "internal_error": (500, "An unexpected error occurred."),
    "not_found": (404, "The requested endpoint does not exist."),
    "method_not_allowed": (405, "The HTTP method is not allowed for this endpoint."),
    "empty_upload": (400, "The uploaded image is empty."),
    "malformed_request": (400, "A valid multipart request with one 'image' field is required."),
    "invalid_batch": (400, "A multipart request with 1 to 5 'images' fields is required."),
    "image_too_large": (413, "The image exceeds the 10 MiB limit."),
    "image_dimensions_too_large": (413, "The decoded image dimensions are too large."),
    "request_too_large": (413, "The request body is too large."),
    "batch_too_large": (413, "The combined image data exceeds the 25 MiB limit."),
    "unsupported_image_format": (415, "Only JPG/JPEG, PNG, and GIF images are supported."),
    "corrupt_image": (422, "The image is corrupt or unreadable."),
    "ocr_unavailable": (503, "The OCR service is temporarily unavailable."),
    "ocr_deadline_exceeded": (504, "The OCR service did not respond in time."),
}


class AppError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code, self.message = ERRORS[code]
        super().__init__(self.message)


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


class BatchItem(BaseModel):
    index: int = Field(ge=0)
    status_code: int = Field(ge=200, le=599)
    success: bool
    processing_time_ms: int = Field(ge=0)
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    normalized_text: str | None = None
    metadata: ImageMetadata | None = None
    error: ErrorDetail | None = None


class BatchResponse(BaseModel):
    success: bool = True
    results: list[BatchItem]
    processing_time_ms: int = Field(ge=0)


class HealthResponse(BaseModel):
    status: str = "ok"
