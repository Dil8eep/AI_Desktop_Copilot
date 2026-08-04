"""Construct provider clients from credentials resolved at operation start."""

from groq import AsyncGroq
from openai import AsyncOpenAI

from app.infrastructure.provider_credential_resolver import (
    ProviderCredentialResolver,
    ResolvedCredential,
)


class ProviderClientFactory:
    """Build short-lived SDK clients while keeping credential resolution centralized."""

    def __init__(
        self, resolver: ProviderCredentialResolver, openai_timeout_seconds: float
    ) -> None:
        self._resolver = resolver
        self._openai_timeout_seconds = openai_timeout_seconds

    async def openai(self) -> tuple[AsyncOpenAI, ResolvedCredential]:
        resolved = await self._resolver.resolve("openai")
        return (
            AsyncOpenAI(
                api_key=resolved.credential,
                timeout=self._openai_timeout_seconds,
            ),
            resolved,
        )

    async def groq(self) -> tuple[AsyncGroq, ResolvedCredential]:
        resolved = await self._resolver.resolve("groq")
        return AsyncGroq(api_key=resolved.credential), resolved
