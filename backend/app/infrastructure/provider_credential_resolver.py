"""Resolve active encrypted credentials with bounded in-memory caching."""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.infrastructure.credential_cipher import CredentialCipher


class ActiveCredentialReader(Protocol):
    async def active_encrypted(self, provider: str) -> dict[str, Any] | None: ...


class CredentialResolutionError(Exception):
    """A usable provider credential could not be resolved."""


@dataclass(frozen=True)
class ResolvedCredential:
    provider: str
    credential: str
    model: str | None
    source: str
    version_id: str | None


@dataclass(frozen=True)
class _CacheEntry:
    value: ResolvedCredential
    expires_at: float


class ProviderCredentialResolver:
    """Prefer managed credentials and fall back explicitly to environment values."""

    def __init__(
        self,
        repository: ActiveCredentialReader | None,
        cipher: CredentialCipher | None,
        environment_credentials: dict[str, tuple[str, str | None]],
        cache_seconds: float = 15,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._environment_credentials = environment_credentials
        self._cache_seconds = cache_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def resolve(self, provider: str) -> ResolvedCredential:
        cached = self._cache.get(provider)
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.value
        async with self._lock:
            cached = self._cache.get(provider)
            now = time.monotonic()
            if cached is not None and cached.expires_at > now:
                return cached.value
            resolved = await self._load(provider)
            self._cache[provider] = _CacheEntry(resolved, now + self._cache_seconds)
            return resolved

    async def _load(self, provider: str) -> ResolvedCredential:
        if self._repository is not None and self._cipher is not None:
            active = await self._repository.active_encrypted(provider)
            if active is not None:
                credential_id = str(active["id"])
                purpose = str(active["purpose"])
                associated_data = f"{provider}:{purpose}:{credential_id}"
                try:
                    credential = self._cipher.decrypt(
                        bytes(active["nonce"]),
                        bytes(active["ciphertext"]),
                        associated_data,
                    )
                except Exception as error:
                    raise CredentialResolutionError(
                        "managed_credential_decryption_failed"
                    ) from error
                model_value = active.get("model")
                return ResolvedCredential(
                    provider,
                    credential,
                    str(model_value) if model_value is not None else None,
                    "managed",
                    credential_id,
                )
        fallback = self._environment_credentials.get(provider)
        if fallback is None or not fallback[0]:
            raise CredentialResolutionError("provider_not_configured")
        return ResolvedCredential(
            provider, fallback[0], fallback[1], "environment", None
        )

    def invalidate(self, provider: str) -> None:
        self._cache.pop(provider, None)
