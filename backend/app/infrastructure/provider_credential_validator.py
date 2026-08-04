"""Minimal provider authentication and model-access checks."""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from groq import AsyncGroq
from openai import AsyncOpenAI


@dataclass(frozen=True)
class CredentialValidation:
    valid: bool
    error_code: str | None = None


class ProviderCredentialValidator(Protocol):
    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation: ...


class LiveProviderCredentialValidator:
    """Validate credentials and optional model access without raw provider errors."""

    def __init__(self, timeout_seconds: float = 12) -> None:
        self._timeout_seconds = timeout_seconds

    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        if provider == "openai":
            if not credential.startswith("sk-"):
                return CredentialValidation(False, "credential_format_invalid")
            operation = self._list_openai_models(credential)
        elif provider == "groq":
            if not credential.startswith("gsk_"):
                return CredentialValidation(False, "credential_format_invalid")
            operation = self._list_groq_models(credential)
        else:
            return CredentialValidation(False, "provider_not_supported")
        try:
            available_models = await asyncio.wait_for(
                operation, timeout=self._timeout_seconds
            )
            if model and model not in available_models:
                return CredentialValidation(False, "provider_model_not_available")
            return CredentialValidation(True)
        except TimeoutError:
            return CredentialValidation(False, "provider_timeout")
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            if status_code in {401, 403}:
                code = "provider_authentication_failed"
            elif status_code == 429:
                code = "provider_rate_limited"
            elif isinstance(status_code, int) and status_code >= 500:
                code = "provider_unavailable"
            else:
                code = "provider_validation_failed"
            return CredentialValidation(False, code)

    async def _list_openai_models(self, credential: str) -> set[str]:
        response = await AsyncOpenAI(
            api_key=credential, timeout=self._timeout_seconds
        ).models.list()
        return self._model_ids(response)

    @staticmethod
    async def _list_groq_models(credential: str) -> set[str]:
        response = await AsyncGroq(api_key=credential).models.list()
        return LiveProviderCredentialValidator._model_ids(response)

    @staticmethod
    def _model_ids(response: Any) -> set[str]:
        return {
            str(model.id)
            for model in getattr(response, "data", [])
            if isinstance(getattr(model, "id", None), str)
        }
