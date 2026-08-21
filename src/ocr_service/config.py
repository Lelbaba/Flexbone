from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCR_", frozen=True)

    max_image_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    request_overhead_bytes: int = 1024 * 1024
    max_batch_images: int = 5
    max_batch_image_bytes: int = 25 * 1024 * 1024
    batch_max_concurrency: int = 2
    batch_timeout_seconds: float = 50.0
    request_timeout_seconds: float = 50.0
    vision_timeout_seconds: float = 20.0
    vision_max_retries: int = 2
    public_docs_url: str = "https://ocr.lelbaba.top/api-docs.html"

    @property
    def max_request_bytes(self) -> int:
        return self.max_image_bytes + self.request_overhead_bytes

    @property
    def max_batch_request_bytes(self) -> int:
        return self.max_batch_image_bytes + self.request_overhead_bytes
