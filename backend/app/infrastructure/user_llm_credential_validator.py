"""Inference-path validation for user-owned LLM credentials."""

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import AsyncOpenAI

from app.infrastructure.provider_credential_validator import CredentialValidation


class LiveUserLlmCredentialValidator:
    """Validate provider auth and model access with a minimal generation."""

    _OPENAI_COMPATIBLE_BASE_URLS = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    }

    def __init__(self, timeout_seconds: float = 15) -> None:
        self._timeout_seconds = timeout_seconds

    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        if not credential.strip():
            return CredentialValidation(False, "credential_format_invalid")
        if model is None or not model.strip():
            return CredentialValidation(False, "provider_model_invalid")
        try:
            if provider == "openai":
                await self._validate_openai(credential, model)
            elif provider in self._OPENAI_COMPATIBLE_BASE_URLS:
                await self._validate_openai_compatible(provider, credential, model)
            elif provider == "ollama_cloud":
                await asyncio.wait_for(
                    asyncio.to_thread(self._validate_ollama_cloud, credential, model),
                    timeout=self._timeout_seconds,
                )
            else:
                return CredentialValidation(False, "provider_not_supported")
            return CredentialValidation(True)
        except TimeoutError:
            return CredentialValidation(False, "provider_timeout")
        except Exception as error:
            return CredentialValidation(False, self._safe_error_code(error))

    async def _validate_openai(self, credential: str, model: str) -> None:
        client = AsyncOpenAI(api_key=credential, timeout=self._timeout_seconds)
        await client.responses.create(
            model=model,
            input="Reply with OK.",
            max_output_tokens=8,
        )

    async def _validate_openai_compatible(
        self, provider: str, credential: str, model: str
    ) -> None:
        client = AsyncOpenAI(
            api_key=credential,
            base_url=self._OPENAI_COMPATIBLE_BASE_URLS[provider],
            timeout=self._timeout_seconds,
        )
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=8,
        )

    def _validate_ollama_cloud(self, credential: str, model: str) -> None:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "stream": False,
                "options": {"num_predict": 8},
            }
        ).encode("utf-8")
        request = Request(
            "https://ollama.com/api/chat",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
            if response.status >= 400:
                raise RuntimeError("provider_validation_failed")
            json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        status_code = getattr(error, "status_code", None)
        if isinstance(error, HTTPError):
            status_code = error.code
        if status_code in {401, 403}:
            return "provider_authentication_failed"
        if status_code == 404:
            return "provider_model_not_available"
        if status_code in {402, 429}:
            return "provider_quota_unavailable"
        if isinstance(status_code, int) and status_code >= 500:
            return "provider_unavailable"
        if isinstance(error, (URLError, ConnectionError)):
            return "provider_unavailable"
        return "provider_validation_failed"
