"""OpenAI-backed flexible resume profile parser."""

import json
from typing import Any

from openai import AsyncOpenAI

from app.infrastructure.provider_client_factory import ProviderClientFactory
from app.infrastructure.provider_credential_resolver import CredentialResolutionError


class ResumeLlmParser:
    """Convert extracted resume text into flexible structured JSON."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        client_factory: ProviderClientFactory | None = None,
    ) -> None:
        self._client = (
            AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
            if api_key is not None
            else None
        )
        self._model = model
        self._client_factory = client_factory

    async def parse(self, user_id: str, resume_text: str) -> dict[str, Any]:
        """Return a dynamic profile without inventing missing resume facts."""
        del user_id
        prompt = (
            "Extract this resume into valid JSON. Detect headings dynamically and "
            "preserve all meaningful information. Use this shape: candidate object "
            "for contact identity, sections object for normalized common sections, "
            "additional_sections object for uncommon headings, and summary string. "
            "Each section may contain arrays or nested objects. Normalize equivalent "
            "headings such as Work History to experience. Do not invent values; use "
            "empty values only when absent. Return JSON only, without markdown.\n\n"
            f"Resume text:\n{resume_text}"
        )
        client, model = await self._client_for_parse()
        response = await client.responses.create(
            model=model,
            input=prompt,
            temperature=0,
        )
        raw = response.output_text.strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("resume_profile_invalid_json")
        return parsed

    async def _client_for_parse(self) -> tuple[AsyncOpenAI, str]:
        if self._client_factory is not None:
            client, resolved = await self._client_factory.openai()
            return client, resolved.model or self._model
        if self._client is None:
            raise CredentialResolutionError("provider_not_configured")
        return self._client, self._model
