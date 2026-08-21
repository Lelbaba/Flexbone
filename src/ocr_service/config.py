from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCR_", frozen=True)

    max_image_bytes: int = 10 * 1024 * 1024
    request_overhead_bytes: int = 1024 * 1024
    vision_timeout_seconds: float = 20.0
    vision_max_retries: int = 2

    @property
    def max_request_bytes(self) -> int:
        return self.max_image_bytes + self.request_overhead_bytes
