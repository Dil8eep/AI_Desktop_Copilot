"""Per-user LLM credential ownership and API security regressions."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.user_llm import create_user_llm_router
from app.application.user_llm_credential_service import UserLlmCredentialService
from app.infrastructure.auth_service import JwtService
from app.infrastructure.credential_cipher import CredentialCipher
from app.infrastructure.provider_credential_validator import CredentialValidation


class FakeRepository:
    def __init__(self) -> None:
        self.pending: dict[str, dict[str, Any]] = {}
        self.active_by_user: dict[str, dict[str, Any]] = {}
        self.invalid: tuple[str, str, str] | None = None
        self.audits: list[tuple[str, str, str | None, str]] = []

    async def create_pending(
        self,
        credential_id: str,
        user_id: str,
        provider: str,
        model: str,
        ciphertext: bytes,
        nonce: bytes,
        masked_hint: str,
        fingerprint: str,
    ) -> None:
        self.pending[credential_id] = {
            "id": credential_id,
            "user_id": user_id,
            "provider": provider,
            "model": model,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "masked_hint": masked_hint,
            "fingerprint": fingerprint,
        }

    async def activate(self, credential_id: str, user_id: str) -> None:
        pending = self.pending[credential_id]
        assert pending["user_id"] == user_id
        self.active_by_user[user_id] = {
            "provider": pending["provider"],
            "model": pending["model"],
            "status": "active",
            "masked_hint": pending["masked_hint"],
            "last_validated_at": datetime(2026, 8, 5, tzinfo=UTC),
            "last_error_code": None,
        }

    async def mark_invalid(
        self, credential_id: str, user_id: str, error_code: str
    ) -> None:
        self.invalid = (credential_id, user_id, error_code)

    async def active_metadata(self, user_id: str) -> dict[str, Any] | None:
        return self.active_by_user.get(user_id)

    async def retire_active(self, user_id: str) -> bool:
        return self.active_by_user.pop(user_id, None) is not None

    async def append_audit(
        self,
        user_id: str,
        action: str,
        provider: str | None,
        result: str,
        correlation_id: str,
    ) -> None:
        del correlation_id
        self.audits.append((user_id, action, provider, result))


class FakeValidator:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[tuple[str, str, str | None]] = []

    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        self.calls.append((provider, credential, model))
        return CredentialValidation(
            self.valid,
            None if self.valid else "provider_authentication_failed",
        )


def build_service(
    repository: FakeRepository, validator: FakeValidator
) -> UserLlmCredentialService:
    return UserLlmCredentialService(
        repository,
        validator,
        CredentialCipher(CredentialCipher.generate_master_key()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", ["openai", "groq", "openrouter", "gemini", "ollama_cloud"]
)
async def test_supported_provider_is_validated(provider: str) -> None:
    validator = FakeValidator()
    service = build_service(FakeRepository(), validator)

    result = await service.validate_only(provider, "private-key", "model-id")

    assert result.valid is True
    assert validator.calls == [(provider, "private-key", "model-id")]


@pytest.mark.asyncio
async def test_unsupported_provider_is_rejected_before_network_validation() -> None:
    validator = FakeValidator()
    service = build_service(FakeRepository(), validator)

    with pytest.raises(ValueError, match="provider_not_supported"):
        await service.validate_only("custom-url", "private-key", "model-id")

    assert validator.calls == []


@pytest.mark.asyncio
async def test_valid_key_is_encrypted_and_activated_for_only_its_user() -> None:
    repository = FakeRepository()
    service = build_service(repository, FakeValidator())

    result = await service.replace(
        "11111111-1111-1111-1111-111111111111",
        "openrouter",
        "user-private-key",
        "provider/free-model",
    )

    pending = next(iter(repository.pending.values()))
    assert result.activated is True
    assert b"user-private-key" not in pending["ciphertext"]
    assert list(repository.active_by_user) == ["11111111-1111-1111-1111-111111111111"]


@pytest.mark.asyncio
async def test_invalid_replacement_keeps_existing_user_configuration() -> None:
    repository = FakeRepository()
    user_id = "11111111-1111-1111-1111-111111111111"
    repository.active_by_user[user_id] = {
        "provider": "openai",
        "model": "old-model",
        "status": "active",
        "masked_hint": "...old1",
        "last_validated_at": None,
    }
    service = build_service(repository, FakeValidator(False))

    result = await service.replace(
        user_id, "gemini", "invalid-private-key", "new-model"
    )

    assert result.activated is False
    assert repository.active_by_user[user_id]["model"] == "old-model"
    assert repository.invalid is not None


def test_authenticated_api_is_user_scoped_and_never_returns_secret() -> None:
    repository = FakeRepository()
    validator = FakeValidator()
    jwt = JwtService("test-secret-that-is-at-least-32-bytes", 15)
    app = FastAPI()
    app.include_router(
        create_user_llm_router(jwt, build_service(repository, validator))
    )
    client = TestClient(app)
    first_user = "11111111-1111-1111-1111-111111111111"
    second_user = "22222222-2222-2222-2222-222222222222"
    first_headers = {"Authorization": f"Bearer {jwt.issue_access_token(first_user)}"}
    second_headers = {"Authorization": f"Bearer {jwt.issue_access_token(second_user)}"}

    response = client.put(
        "/api/llm/config",
        headers=first_headers,
        json={
            "provider": "ollama_cloud",
            "model": "gpt-oss:120b",
            "credential": "ollama-user-private-key",
        },
    )

    assert response.status_code == 200
    assert "ollama-user-private-key" not in response.text
    assert response.json()["maskedHint"] == "...-key"
    assert (
        client.get("/api/llm/config", headers=first_headers).json()["configured"]
        is True
    )
    assert client.get("/api/llm/config", headers=second_headers).json() == {
        "configured": False
    }


def test_user_can_remove_only_their_active_configuration() -> None:
    repository = FakeRepository()
    jwt = JwtService("test-secret-that-is-at-least-32-bytes", 15)
    service = build_service(repository, FakeValidator())
    app = FastAPI()
    app.include_router(create_user_llm_router(jwt, service))
    client = TestClient(app)
    user_id = "11111111-1111-1111-1111-111111111111"
    headers = {"Authorization": f"Bearer {jwt.issue_access_token(user_id)}"}
    repository.active_by_user[user_id] = {
        "provider": "groq",
        "model": "model",
        "status": "active",
        "masked_hint": "...1234",
        "last_validated_at": None,
    }

    response = client.delete("/api/llm/config", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"configured": False, "removed": True}
    assert repository.active_by_user == {}
