"""Per-user encrypted LLM configuration lifecycle."""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.infrastructure.credential_cipher import CredentialCipher, masked_hint
from app.infrastructure.provider_credential_validator import CredentialValidation

SUPPORTED_USER_LLM_PROVIDERS = frozenset(
    {"openai", "groq", "openrouter", "gemini", "ollama_cloud"}
)


class UserLlmCredentialValidator(Protocol):
    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation: ...


class UserLlmCredentialRepository(Protocol):
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
    ) -> None: ...

    async def activate(self, credential_id: str, user_id: str) -> None: ...

    async def mark_invalid(
        self, credential_id: str, user_id: str, error_code: str
    ) -> None: ...

    async def active_metadata(self, user_id: str) -> dict[str, Any] | None: ...

    async def active_material(self, user_id: str) -> dict[str, Any] | None: ...

    async def retire_active(self, user_id: str) -> bool: ...

    async def append_audit(
        self,
        user_id: str,
        action: str,
        provider: str | None,
        result: str,
        correlation_id: str,
    ) -> None: ...


@dataclass(frozen=True)
class ResolvedUserLlmConfiguration:
    provider: str
    model: str
    credential: str


@dataclass(frozen=True)
class UserLlmReplacementResult:
    activated: bool
    provider: str
    model: str
    status: str
    masked_hint: str
    error_code: str | None
    correlation_id: str


class UserLlmCredentialService:
    """Validate and atomically activate one LLM configuration per user."""

    def __init__(
        self,
        repository: UserLlmCredentialRepository,
        validator: UserLlmCredentialValidator,
        cipher: CredentialCipher,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._cipher = cipher

    @staticmethod
    def require_provider(provider: str) -> str:
        normalized = provider.strip().lower()
        if normalized not in SUPPORTED_USER_LLM_PROVIDERS:
            raise ValueError("provider_not_supported")
        return normalized

    @staticmethod
    def require_model(model: str) -> str:
        normalized = model.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("provider_model_invalid")
        return normalized

    async def validate_only(
        self, provider: str, credential: str, model: str
    ) -> CredentialValidation:
        return await self._validator.validate(
            self.require_provider(provider), credential, self.require_model(model)
        )

    async def replace(
        self, user_id: str, provider: str, credential: str, model: str
    ) -> UserLlmReplacementResult:
        normalized_provider = self.require_provider(provider)
        normalized_model = self.require_model(model)
        credential_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())
        associated_data = f"user:{user_id}:{normalized_provider}:llm:{credential_id}"
        nonce, ciphertext = self._cipher.encrypt(credential, associated_data)
        hint = masked_hint(credential)
        await self._repository.create_pending(
            credential_id,
            user_id,
            normalized_provider,
            normalized_model,
            ciphertext,
            nonce,
            hint,
            self._cipher.fingerprint(credential),
        )
        validation = await self._validator.validate(
            normalized_provider, credential, normalized_model
        )
        if not validation.valid:
            error_code = validation.error_code or "provider_validation_failed"
            await self._repository.mark_invalid(credential_id, user_id, error_code)
            await self._repository.append_audit(
                user_id,
                "user_llm_credential_replace",
                normalized_provider,
                "failed",
                correlation_id,
            )
            return UserLlmReplacementResult(
                False,
                normalized_provider,
                normalized_model,
                "invalid",
                hint,
                error_code,
                correlation_id,
            )
        await self._repository.activate(credential_id, user_id)
        await self._repository.append_audit(
            user_id,
            "user_llm_credential_replace",
            normalized_provider,
            "success",
            correlation_id,
        )
        return UserLlmReplacementResult(
            True,
            normalized_provider,
            normalized_model,
            "active",
            hint,
            None,
            correlation_id,
        )

    async def resolve(self, user_id: str) -> ResolvedUserLlmConfiguration:
        material = await self._repository.active_material(user_id)
        if material is None:
            raise ValueError("llm_configuration_required")
        credential_id = str(material["id"])
        provider = self.require_provider(str(material["provider"]))
        model = self.require_model(str(material["model"]))
        associated_data = f"user:{user_id}:{provider}:llm:{credential_id}"
        credential = self._cipher.decrypt(
            bytes(material["nonce"]),
            bytes(material["ciphertext"]),
            associated_data,
        )
        return ResolvedUserLlmConfiguration(provider, model, credential)

    async def metadata(self, user_id: str) -> dict[str, Any] | None:
        return await self._repository.active_metadata(user_id)

    async def remove(self, user_id: str) -> bool:
        correlation_id = str(uuid.uuid4())
        removed = await self._repository.retire_active(user_id)
        await self._repository.append_audit(
            user_id,
            "user_llm_credential_remove",
            None,
            "success" if removed else "not_configured",
            correlation_id,
        )
        return removed
