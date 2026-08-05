"""Milestone 7 deployment-security regressions."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.infrastructure.credential_invalidation_listener import (
    CredentialInvalidationListener,
)
from app.settings import Settings


def test_production_settings_reject_development_security_defaults() -> None:
    with pytest.raises(ValidationError, match="COPILOT_JWT_SECRET"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://user:password@db.example/prod",
            jwt_secret="development-change-this-secret",
            local_auth_token="development-only-token",
            credential_master_key=SecretStr(
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            ),
            force_https=False,
            cors_origins="*",
            allowed_hosts="*",
        )


def test_sensitive_route_rate_limit_and_production_headers() -> None:
    application = FastAPI()
    application.add_middleware(RateLimitMiddleware, login_limit=2, credential_limit=1)
    application.add_middleware(SecurityHeadersMiddleware, production=True)

    @application.post("/api/auth/login")
    async def login() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(application) as client:
        first = client.post("/api/auth/login")
        assert first.status_code == 200
        assert first.headers["x-content-type-options"] == "nosniff"
        assert "max-age=31536000" in first.headers["strict-transport-security"]
        assert client.post("/api/auth/login").status_code == 200
        limited = client.post("/api/auth/login")

    assert limited.status_code == 429
    assert limited.json() == {"error": "rate_limit_exceeded"}
    assert limited.headers["retry-after"] == "60"


def test_user_llm_credentials_are_not_cached_and_are_rate_limited() -> None:
    application = FastAPI()
    application.add_middleware(RateLimitMiddleware, login_limit=2, credential_limit=1)
    application.add_middleware(SecurityHeadersMiddleware, production=False)

    @application.put("/api/llm/config")
    async def replace_user_llm_config() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(application) as client:
        first = client.put("/api/llm/config")
        limited = client.put("/api/llm/config")

    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert limited.status_code == 429


class _Resolver:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    def invalidate(self, provider: str) -> None:
        self.invalidated.append(provider)


def test_database_notification_invalidates_only_known_provider() -> None:
    resolver = _Resolver()
    listener = CredentialInvalidationListener(
        "postgresql://example.invalid/test",
        resolver,  # type: ignore[arg-type]
    )

    listener._on_notification(None, 1, "provider_credential_changed", "openai")
    listener._on_notification(None, 1, "provider_credential_changed", "unknown")

    assert resolver.invalidated == ["openai"]
