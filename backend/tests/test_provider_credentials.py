"""Security regressions for encrypted provider credential rotation."""

from typing import Any

import pytest
from cryptography.exceptions import InvalidTag

from app.application.provider_credential_service import ProviderCredentialService
from app.infrastructure.credential_cipher import CredentialCipher, masked_hint
from app.infrastructure.provider_credential_validator import CredentialValidation


class FakeCredentialRepository:
    def __init__(self) -> None:
        self.pending: dict[str, Any] | None = None
        self.activated: str | None = None
        self.invalid_error: str | None = None
        self.audits: list[tuple[str, str]] = []
        self.retired: dict[str, Any] | None = None
        self.rolled_back: str | None = None

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
        self.pending = {
            "id": credential_id,
            "provider": provider,
            "purpose": purpose,
            "model": model,
            "ciphertext": ciphertext,
            "nonce": nonce,
            "hint": hint,
            "fingerprint": fingerprint,
            "actor": actor_user_id,
        }

    async def activate(self, credential_id: str, provider: str) -> None:
        self.activated = credential_id

    async def mark_invalid(self, credential_id: str, error_code: str) -> None:
        self.invalid_error = error_code

    async def latest_retired_encrypted(self, provider: str) -> dict[str, Any] | None:
        return self.retired

    async def rollback_to(self, credential_id: str, provider: str) -> None:
        self.rolled_back = credential_id

    async def active_metadata(self) -> list[dict[str, Any]]:
        return []

    async def append_audit(
        self,
        actor_user_id: str,
        action: str,
        target_id: str,
        result: str,
        correlation_id: str,
    ) -> None:
        self.audits.append((result, target_id))


class FakeValidator:
    def __init__(self, validation: CredentialValidation) -> None:
        self.validation = validation

    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        return self.validation


def test_cipher_round_trip_and_authenticated_tamper_detection() -> None:
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    nonce, encrypted = cipher.encrypt("sk-private-value", "openai:llm:id")

    assert cipher.decrypt(nonce, encrypted, "openai:llm:id") == "sk-private-value"
    with pytest.raises(InvalidTag):
        cipher.decrypt(nonce, encrypted, "groq:stt:id")


def test_masked_hint_never_returns_more_than_four_secret_characters() -> None:
    assert masked_hint("sk-example-123456") == "...3456"
    assert masked_hint("abc") == "..."


@pytest.mark.asyncio
async def test_valid_credential_is_encrypted_then_activated() -> None:
    repository = FakeCredentialRepository()
    service = ProviderCredentialService(
        repository,
        FakeValidator(CredentialValidation(True)),
        CredentialCipher(CredentialCipher.generate_master_key()),
    )

    result = await service.replace(
        "openai", "sk-private-value", "gpt-test", "admin-user"
    )

    assert result.activated is True
    assert repository.activated == repository.pending["id"]
    assert b"sk-private-value" not in repository.pending["ciphertext"]
    assert repository.audits == [("success", "openai")]


@pytest.mark.asyncio
async def test_invalid_credential_never_replaces_active_version() -> None:
    repository = FakeCredentialRepository()
    service = ProviderCredentialService(
        repository,
        FakeValidator(CredentialValidation(False, "provider_authentication_failed")),
        CredentialCipher(CredentialCipher.generate_master_key()),
    )

    result = await service.replace(
        "groq", "gsk_invalid-value", "whisper-test", "admin-user"
    )

    assert result.activated is False
    assert repository.activated is None
    assert repository.invalid_error == "provider_authentication_failed"
    assert repository.audits == [("failed", "groq")]


@pytest.mark.asyncio
async def test_rollback_validates_previous_key_before_activation() -> None:
    repository = FakeCredentialRepository()
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    credential_id = "79c866d4-5f23-4b58-bc77-3c49bd5e0128"
    nonce, ciphertext = cipher.encrypt("sk-previous-key", f"openai:llm:{credential_id}")
    repository.retired = {
        "id": credential_id,
        "purpose": "llm",
        "model": "previous-model",
        "nonce": nonce,
        "ciphertext": ciphertext,
        "masked_hint": "...-key",
    }
    service = ProviderCredentialService(
        repository, FakeValidator(CredentialValidation(True)), cipher
    )

    result = await service.rollback("openai", "admin-user")

    assert result.activated is True
    assert repository.rolled_back == credential_id
    assert repository.audits == [("success", "openai")]


@pytest.mark.asyncio
async def test_failed_rollback_keeps_current_key_active() -> None:
    repository = FakeCredentialRepository()
    cipher = CredentialCipher(CredentialCipher.generate_master_key())
    credential_id = "79c866d4-5f23-4b58-bc77-3c49bd5e0128"
    nonce, ciphertext = cipher.encrypt("sk-revoked-key", f"openai:llm:{credential_id}")
    repository.retired = {
        "id": credential_id,
        "purpose": "llm",
        "model": "previous-model",
        "nonce": nonce,
        "ciphertext": ciphertext,
        "masked_hint": "...-key",
    }
    service = ProviderCredentialService(
        repository,
        FakeValidator(CredentialValidation(False, "provider_authentication_failed")),
        cipher,
    )

    result = await service.rollback("openai", "admin-user")

    assert result.activated is False
    assert repository.rolled_back is None
    assert repository.audits == [("failed", "openai")]
