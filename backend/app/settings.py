"""Validated application configuration loaded at the composition root."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime values; provider keys remain backend-only configuration."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_prefix="COPILOT_",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8765
    database_url: str = "postgresql+asyncpg://copilot_user:change-this-password@127.0.0.1:5434/ai_desktop_copilot"
    jwt_secret: str = "development-change-this-secret"
    jwt_access_token_minutes: int = Field(default=15, gt=1, le=60)
    jwt_refresh_token_days: int = Field(default=30, gt=1, le=365)
    bootstrap_admin_email: str | None = None
    credential_master_key: SecretStr | None = None
    credential_cache_seconds: float = Field(default=15, gt=0, le=300)
    cors_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:5174,http://localhost:5174,null"
    )
    allowed_hosts: str = "127.0.0.1,localhost,testserver"
    force_https: bool = False
    login_rate_limit_per_minute: int = Field(default=10, ge=1, le=300)
    credential_rate_limit_per_minute: int = Field(default=6, ge=1, le=60)
    resume_upload_directory: str = "uploads/resumes"
    resume_max_file_bytes: int = Field(default=10_000_000, gt=0, le=50_000_000)
    local_auth_token: str = "development-only-token"
    llm_provider: str = "openai"
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("COPILOT_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = Field(default=45, gt=0, le=120)
    auto_respond_to_speech: bool = True
    console_transcript_logging: bool = True
    context_transcript_characters: int = Field(default=6_000, ge=500, le=20_000)
    context_screen_characters: int = Field(default=4_000, ge=500, le=12_000)
    speech_provider: str = "groq"
    groq_api_key: SecretStr | None = None
    groq_whisper_model: str = "whisper-large-v3"
    speech_timeout_seconds: float = Field(default=30, gt=0, le=120)
    mock_llm_token_delay_ms: int = Field(default=20, ge=0, le=1_000)
    ocr_provider: str = "liteparse"

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [
            value.strip() for value in self.cors_origins.split(",") if value.strip()
        ]

    @property
    def parsed_allowed_hosts(self) -> list[str]:
        return [
            value.strip() for value in self.allowed_hosts.split(",") if value.strip()
        ]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment != "production":
            return self
        errors: list[str] = []
        if (
            len(self.jwt_secret) < 32
            or self.jwt_secret == "development-change-this-secret"
        ):
            errors.append("COPILOT_JWT_SECRET must be a unique 32+ character secret")
        if self.credential_master_key is None:
            errors.append("COPILOT_CREDENTIAL_MASTER_KEY is required")
        if not self.force_https:
            errors.append("COPILOT_FORCE_HTTPS must be true")
        if not self.parsed_cors_origins or "*" in self.parsed_cors_origins:
            errors.append("COPILOT_CORS_ORIGINS must explicitly list trusted origins")
        if not self.parsed_allowed_hosts or "*" in self.parsed_allowed_hosts:
            errors.append("COPILOT_ALLOWED_HOSTS must explicitly list trusted hosts")
        if "127.0.0.1" in self.database_url or "localhost" in self.database_url:
            errors.append("COPILOT_DATABASE_URL must reference a production database")
        if errors:
            raise ValueError("; ".join(errors))
        return self
