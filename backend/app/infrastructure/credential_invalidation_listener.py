"""PostgreSQL LISTEN/NOTIFY invalidation for credential caches."""

import logging
from typing import Any

from app.infrastructure.provider_credential_resolver import ProviderCredentialResolver

logger = logging.getLogger("copilot.credentials")


class CredentialInvalidationListener:
    """Invalidate this worker when another worker rotates a provider key."""

    _channel = "provider_credential_changed"

    def __init__(self, database_url: str, resolver: ProviderCredentialResolver) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._resolver = resolver
        self._connection: Any | None = None

    async def start(self) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        await connection.add_listener(self._channel, self._on_notification)
        self._connection = connection
        logger.info("credential_invalidation_listener_started")

    async def stop(self) -> None:
        if self._connection is None:
            return
        await self._connection.remove_listener(self._channel, self._on_notification)
        await self._connection.close()
        self._connection = None
        logger.info("credential_invalidation_listener_stopped")

    def _on_notification(
        self, connection: Any, process_id: int, channel: str, payload: str
    ) -> None:
        del connection, process_id, channel
        if payload in {"openai", "groq"}:
            self._resolver.invalidate(payload)
            logger.info("credential_cache_invalidated provider=%s", payload)
