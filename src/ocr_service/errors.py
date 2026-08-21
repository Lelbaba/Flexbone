class AppError(Exception):
    code = "internal_error"
    message = "An unexpected error occurred."
    status_code = 500


class EmptyUpload(AppError):
    code = "empty_upload"
    message = "The uploaded image is empty."
    status_code = 400


class MalformedRequest(AppError):
    code = "malformed_request"
    message = "A valid multipart request with one 'image' field is required."
    status_code = 400


class InvalidBatch(AppError):
    code = "invalid_batch"
    message = "A multipart request with 1 to 5 'images' fields is required."
    status_code = 400


class ImageTooLarge(AppError):
    code = "image_too_large"
    message = "The image exceeds the 10 MiB limit."
    status_code = 413


class ImageDimensionsTooLarge(AppError):
    code = "image_dimensions_too_large"
    message = "The decoded image dimensions are too large."
    status_code = 413


class RequestTooLarge(AppError):
    code = "request_too_large"
    message = "The request body is too large."
    status_code = 413


class BatchTooLarge(AppError):
    code = "batch_too_large"
    message = "The combined image data exceeds the 25 MiB limit."
    status_code = 413


class UnsupportedImageFormat(AppError):
    code = "unsupported_image_format"
    message = "Only JPG/JPEG, PNG, and GIF images are supported."
    status_code = 415


class CorruptImage(AppError):
    code = "corrupt_image"
    message = "The image is corrupt or unreadable."
    status_code = 422


class OCRUnavailable(AppError):
    code = "ocr_unavailable"
    message = "The OCR service is temporarily unavailable."
    status_code = 503


class OCRDeadlineExceeded(AppError):
    code = "ocr_deadline_exceeded"
    message = "The OCR service did not respond in time."
    status_code = 504
