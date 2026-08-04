"""Runtime credential resolution, caching, fallback, and rotation tests."""

import uuid
from typing import Any

import pytest

from app.application.provider_credential_service import ProviderCredentialService
from app.infrastructure.credential_cipher import CredentialCipher
from app.infrastructure.provider_credential_resolver import (
    CredentialResolutionError,
    ProviderCredentialResolver,
)
from app.infrastructure.provider_credential_validator import CredentialValidation


class ManagedRepository:
    def __init__(self) -> None:
        self.active: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, dict[str, Any]] = {}

    async def active_encrypted(self, provider: str) -> dict[str, Any] | None:
        return self.active.get(provider)

    async def create_pending(
        self,
        credential_id: str,
        provider: str,
        purpose: str,
        model: str | None,
        ciphertext: bytes,
        nonce: bytes,
        hint: str,
        fingerprint: str,
        actor_user_id: str,
    ) -> None:
        self.pending[credential_id] = {
            "id": credential_id,
            "provider": provider,
            "purpose": purpose,
            "model": model,
            "ciphertext": ciphertext,
            "nonce": nonce,
        }

    async def activate(self, credential_id: str, provider: str) -> None:
        self.active[provider] = self.pending[credential_id]

    async def mark_invalid(self, credential_id: str, error_code: str) -> None:
        return None

    async def active_metadata(self) -> list[dict[str, Any]]:
        return []

    async def append_audit(self, *args: Any) -> None:
        return None


class ValidValidator:
    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        return CredentialValidation(True)


def encrypted_row(
    cipher: CredentialCipher,
    provider: str,
    purpose: str,
    credential: str,
    model: str,
) -> dict[str, Any]:
    credential_id = str(uuid.uuid4())
    nonce, ciphertext = cipher.encrypt(
        credential, f"{provider}:{purpose}:{credential_id}"
    )
    return {
        "id": credential_id,
        "provider": provider,
        "purpose": purpose,
        "model": model,
        "ciphertext": ciphertext,
        "nonce": nonce,
    }


@pytest.mark.asyncio
async def test_managed_credential_takes_priority_over_environment() -> None:
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    repository = ManagedRepository()
    repository.active["openai"] = encrypted_row(
        cipher, "openai", "llm", "sk-managed", "managed-model"
    )
    resolver = ProviderCredentialResolver(
        repository,
        cipher,
        {"openai": ("sk-environment", "environment-model")},
        60,
    )

    resolved = await resolver.resolve("openai")

    assert resolved.credential == "sk-managed"
    assert resolved.model == "managed-model"
    assert resolved.source == "managed"


@pytest.mark.asyncio
async def test_environment_is_explicit_fallback_when_no_managed_version() -> None:
    resolver = ProviderCredentialResolver(
        ManagedRepository(),
        CredentialCipher(CredentialCipher.generate_master_key()),
        {"groq": ("gsk_environment", "whisper-environment")},
        60,
    )

    resolved = await resolver.resolve("groq")

    assert resolved.credential == "gsk_environment"
    assert resolved.source == "environment"


@pytest.mark.asyncio
async def test_rotation_invalidates_cache_for_next_operation_only() -> None:
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    repository = ManagedRepository()
    repository.active["openai"] = encrypted_row(
        cipher, "openai", "llm", "sk-old-key", "old-model"
    )
    resolver = ProviderCredentialResolver(repository, cipher, {}, 60)
    service = ProviderCredentialService(repository, ValidValidator(), cipher, resolver)
    in_flight = await resolver.resolve("openai")

    result = await service.replace("openai", "sk-new-key", "new-model", "admin-user")
    next_operation = await resolver.resolve("openai")

    assert result.activated is True
    assert in_flight.credential == "sk-old-key"
    assert in_flight.model == "old-model"
    assert next_operation.credential == "sk-new-key"
    assert next_operation.model == "new-model"


@pytest.mark.asyncio
async def test_corrupt_managed_ciphertext_never_falls_back_silently() -> None:
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    repository = ManagedRepository()
    row = encrypted_row(cipher, "openai", "llm", "sk-managed", "model")
    row["ciphertext"] = bytes(row["ciphertext"])[:-1] + b"x"
    repository.active["openai"] = row
    resolver = ProviderCredentialResolver(
        repository, cipher, {"openai": ("sk-fallback", "fallback")}, 60
    )

    with pytest.raises(
        CredentialResolutionError, match="managed_credential_decryption_failed"
    ):
        await resolver.resolve("openai")
