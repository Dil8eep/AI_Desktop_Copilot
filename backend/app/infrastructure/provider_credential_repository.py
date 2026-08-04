"""Versioned encrypted provider-credential persistence."""

import uuid
from typing import Any


class ProviderCredentialRepository:
    """Persist ciphertext and safe metadata; plaintext never reaches PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    @staticmethod
    async def _ensure_schema(connection: Any) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_credentials (
                id UUID PRIMARY KEY,
                provider TEXT NOT NULL,
                purpose TEXT NOT NULL,
                model TEXT,
                ciphertext BYTEA NOT NULL,
                nonce BYTEA NOT NULL,
                encryption_algorithm TEXT NOT NULL DEFAULT 'AES-256-GCM',
                masked_hint TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                last_validated_at TIMESTAMPTZ,
                last_error_code TEXT,
                created_by UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                activated_at TIMESTAMPTZ,
                retired_at TIMESTAMPTZ
            )
            """
        )
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS provider_credentials_one_active
            ON provider_credentials (provider) WHERE status = 'active'
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_events (
                id UUID PRIMARY KEY,
                actor_user_id UUID,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                result TEXT NOT NULL,
                correlation_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

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
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                INSERT INTO provider_credentials (
                    id, provider, purpose, model, ciphertext, nonce, masked_hint,
                    fingerprint, status, created_by
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pending',$9)
                """,
                uuid.UUID(credential_id),
                provider,
                purpose,
                model,
                ciphertext,
                nonce,
                hint,
                fingerprint,
                uuid.UUID(actor_user_id),
            )
        finally:
            await connection.close()

    async def activate(self, credential_id: str, provider: str) -> None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            async with connection.transaction():
                pending = await connection.fetchval(
                    """
                    SELECT id FROM provider_credentials
                    WHERE id=$1 AND provider=$2 AND status='pending'
                    FOR UPDATE
                    """,
                    uuid.UUID(credential_id),
                    provider,
                )
                if pending is None:
                    raise RuntimeError("pending_credential_not_found")
                await connection.execute(
                    """
                    UPDATE provider_credentials
                    SET status='retired', retired_at=NOW()
                    WHERE provider=$1 AND status='active'
                    """,
                    provider,
                )
                await connection.execute(
                    """
                    UPDATE provider_credentials
                    SET status='active', activated_at=NOW(),
                        last_validated_at=NOW(), last_error_code=NULL
                    WHERE id=$1 AND provider=$2 AND status='pending'
                    """,
                    uuid.UUID(credential_id),
                    provider,
                )
                await connection.execute(
                    "SELECT pg_notify('provider_credential_changed', $1)",
                    provider,
                )
        finally:
            await connection.close()

    async def mark_invalid(self, credential_id: str, error_code: str) -> None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                UPDATE provider_credentials
                SET status='invalid', last_validated_at=NOW(), last_error_code=$2
                WHERE id=$1 AND status='pending'
                """,
                uuid.UUID(credential_id),
                error_code,
            )
        finally:
            await connection.close()

    async def latest_retired_encrypted(self, provider: str) -> dict[str, Any] | None:
        """Return the most recently retired version for validated rollback."""
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                """
                SELECT id::text, provider, purpose, model, ciphertext, nonce,
                       masked_hint
                FROM provider_credentials
                WHERE provider=$1 AND status='retired'
                ORDER BY retired_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                provider,
            )
            return dict(row) if row is not None else None
        finally:
            await connection.close()

    async def rollback_to(self, credential_id: str, provider: str) -> None:
        """Atomically exchange the active and selected retired versions."""
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            async with connection.transaction():
                target = await connection.fetchval(
                    """
                    SELECT id FROM provider_credentials
                    WHERE id=$1 AND provider=$2 AND status='retired'
                    FOR UPDATE
                    """,
                    uuid.UUID(credential_id),
                    provider,
                )
                if target is None:
                    raise RuntimeError("rollback_credential_not_found")
                await connection.execute(
                    """
                    UPDATE provider_credentials
                    SET status='retired', retired_at=NOW()
                    WHERE provider=$1 AND status='active'
                    """,
                    provider,
                )
                await connection.execute(
                    """
                    UPDATE provider_credentials
                    SET status='active', activated_at=NOW(), retired_at=NULL,
                        last_validated_at=NOW(), last_error_code=NULL
                    WHERE id=$1 AND provider=$2 AND status='retired'
                    """,
                    uuid.UUID(credential_id),
                    provider,
                )
                await connection.execute(
                    "SELECT pg_notify('provider_credential_changed', $1)",
                    provider,
                )
        finally:
            await connection.close()

    async def active_encrypted(self, provider: str) -> dict[str, Any] | None:
        """Return one active encrypted version for backend-only resolution."""
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                """
                SELECT id::text, provider, purpose, model, ciphertext, nonce
                FROM provider_credentials
                WHERE provider=$1 AND status='active'
                """,
                provider,
            )
            return dict(row) if row is not None else None
        finally:
            await connection.close()

    async def active_metadata(self) -> list[dict[str, Any]]:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            rows = await connection.fetch(
                """
                SELECT c.provider, c.purpose, c.model, c.masked_hint, c.status,
                       c.last_validated_at, c.last_error_code, c.activated_at,
                       EXISTS (
                           SELECT 1 FROM provider_credentials r
                           WHERE r.provider=c.provider AND r.status='retired'
                       ) AS can_rollback
                FROM provider_credentials c WHERE c.status='active'
                ORDER BY c.provider
                """
            )
            return [dict(row) for row in rows]
        finally:
            await connection.close()

    async def append_audit(
        self,
        actor_user_id: str,
        action: str,
        target_id: str,
        result: str,
        correlation_id: str,
    ) -> None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                INSERT INTO admin_audit_events (
                    id, actor_user_id, action, target_type, target_id,
                    result, correlation_id
                ) VALUES ($1,$2,$3,'provider',$4,$5,$6)
                """,
                uuid.uuid4(),
                uuid.UUID(actor_user_id),
                action,
                target_id,
                result,
                correlation_id,
            )
        finally:
            await connection.close()
