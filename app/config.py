"""환경변수 설정. 배포 호스트의 .env는 Compose만 읽는다."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FMH_", extra="ignore", hide_input_in_errors=True,
    )

    environment: str = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg2://admin:admin@localhost:5432/fmh")
    session_secret: SecretStr = SecretStr("development-only-change-this-secret")
    session_cookie: str = "fmh_session"
    session_hours: int = Field(default=12, ge=1, le=720)
    cookie_secure: bool = False
    public_origin: str = "http://localhost:8000"
    trusted_proxy_ips: str = "127.0.0.1,::1"
    storage_dir: Path = Path(".runtime/media")
    log_dir: Path = Path(".runtime/logs")
    log_max_bytes: int = Field(default=20_000_000, ge=1024)
    log_backups: int = Field(default=10, ge=1)
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    worker_poll_seconds: float = Field(default=1, ge=0.05)
    pdf_font: Path = Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
    seed_password: SecretStr = SecretStr("")
    seed_demo: bool = False

    @model_validator(mode="after")
    def production_secrets(self):
        if self.environment == "production":
            secret = self.session_secret.get_secret_value()
            if secret.startswith(("development-", "replace_")):
                raise ValueError("운영 FMH_SESSION_SECRET의 예시값을 실제 무작위 비밀값으로 변경하세요.")
            if len(secret) < 32:
                raise ValueError("운영 FMH_SESSION_SECRET은 32자 이상이어야 합니다.")
            if not self.cookie_secure:
                raise ValueError("운영 세션 쿠키에는 Secure가 필요합니다.")
            if not self.database_url.get_secret_value().startswith("postgresql"):
                raise ValueError("운영 환경은 PostgreSQL을 사용해야 합니다.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
