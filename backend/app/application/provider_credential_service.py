"""Secure provider credential validation and activation workflow."""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.infrastructure.credential_cipher import CredentialCipher, masked_hint
from app.infrastructure.provider_credential_validator import (
    CredentialValidation,
    ProviderCredentialValidator,
)


class CredentialCacheInvalidator(Protocol):
    def invalidate(self, provider: str) -> None: ...


class CredentialRepository(Protocol):
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
    ) -> None: ...

    async def activate(self, credential_id: str, provider: str) -> None: ...

    async def mark_invalid(self, credential_id: str, error_code: str) -> None: ...

    async def latest_retired_encrypted(
        self, provider: str
    ) -> dict[str, Any] | None: ...

    async def rollback_to(self, credential_id: str, provider: str) -> None: ...

    async def active_metadata(self) -> list[dict[str, Any]]: ...

    async def append_audit(
        self,
        actor_user_id: str,
        action: str,
        target_id: str,
        result: str,
        correlation_id: str,
    ) -> None: ...


@dataclass(frozen=True)
class ReplacementResult:
    activated: bool
    provider: str
    purpose: str
    model: str | None
    status: str
    masked_hint: str
    error_code: str | None
    correlation_id: str


class ProviderCredentialService:
    """Validate and atomically activate encrypted provider credentials."""

    _PURPOSES = {"openai": "llm", "groq": "stt"}

    def __init__(
        self,
        repository: CredentialRepository,
        validator: ProviderCredentialValidator,
        cipher: CredentialCipher,
        cache_invalidator: CredentialCacheInvalidator | None = None,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._cipher = cipher
        self._cache_invalidator = cache_invalidator

    @classmethod
    def require_provider(cls, provider: str) -> str:
        purpose = cls._PURPOSES.get(provider)
        if purpose is None:
            raise ValueError("provider_not_supported")
        return purpose

    async def validate_only(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        self.require_provider(provider)
        return await self._validator.validate(provider, credential, model)

    async def replace(
        self,
        provider: str,
        credential: str,
        model: str | None,
        actor_user_id: str,
    ) -> ReplacementResult:
        purpose = self.require_provider(provider)
        credential_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())
        associated_data = f"{provider}:{purpose}:{credential_id}"
        nonce, ciphertext = self._cipher.encrypt(credential, associated_data)
        hint = masked_hint(credential)
        await self._repository.create_pending(
            credential_id,
            provider,
            purpose,
            model,
            ciphertext,
            nonce,
            hint,
            self._cipher.fingerprint(credential),
            actor_user_id,
        )
        validation = await self._validator.validate(provider, credential, model)
        if not validation.valid:
            error_code = validation.error_code or "provider_validation_failed"
            await self._repository.mark_invalid(credential_id, error_code)
            await self._repository.append_audit(
                actor_user_id,
                "provider_credential_replace",
                provider,
                "failed",
                correlation_id,
            )
            return ReplacementResult(
                False,
                provider,
                purpose,
                model,
                "invalid",
                hint,
                error_code,
                correlation_id,
            )
        await self._repository.activate(credential_id, provider)
        if self._cache_invalidator is not None:
            self._cache_invalidator.invalidate(provider)
        await self._repository.append_audit(
            actor_user_id,
            "provider_credential_replace",
            provider,
            "success",
            correlation_id,
        )
        return ReplacementResult(
            True,
            provider,
            purpose,
            model,
            "active",
            hint,
            None,
            correlation_id,
        )

    async def rollback(self, provider: str, actor_user_id: str) -> ReplacementResult:
        purpose = self.require_provider(provider)
        correlation_id = str(uuid.uuid4())
        previous = await self._repository.latest_retired_encrypted(provider)
        if previous is None:
            raise ValueError("rollback_credential_not_found")
        credential_id = str(previous["id"])
        associated_data = f"{provider}:{purpose}:{credential_id}"
        try:
            credential = self._cipher.decrypt(
                bytes(previous["nonce"]),
                bytes(previous["ciphertext"]),
                associated_data,
            )
        except Exception as error:
            raise ValueError("rollback_credential_decryption_failed") from error
        model_value = previous.get("model")
        model = str(model_value) if model_value is not None else None
        validation = await self._validator.validate(provider, credential, model)
        if not validation.valid:
            error_code = validation.error_code or "provider_validation_failed"
            await self._repository.append_audit(
                actor_user_id,
                "provider_credential_rollback",
                provider,
                "failed",
                correlation_id,
            )
            return ReplacementResult(
                False,
                provider,
                purpose,
                model,
                "invalid",
                str(previous["masked_hint"]),
                error_code,
                correlation_id,
            )
        await self._repository.rollback_to(credential_id, provider)
        if self._cache_invalidator is not None:
            self._cache_invalidator.invalidate(provider)
        await self._repository.append_audit(
            actor_user_id,
            "provider_credential_rollback",
            provider,
            "success",
            correlation_id,
        )
        return ReplacementResult(
            True,
            provider,
            purpose,
            model,
            "active",
            str(previous["masked_hint"]),
            None,
            correlation_id,
        )

    async def active_metadata(self) -> list[dict[str, Any]]:
        return await self._repository.active_metadata()
