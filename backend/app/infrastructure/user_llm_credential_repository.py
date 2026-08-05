"""Encrypted per-user LLM credential persistence."""

import uuid
from typing import Any


class UserLlmCredentialRepository:
    """Store versioned ciphertext scoped to one authenticated user."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    @staticmethod
    async def _ensure_schema(connection: Any) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_llm_credentials (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT 'llm',
                model TEXT NOT NULL,
                ciphertext BYTEA NOT NULL,
                nonce BYTEA NOT NULL,
                encryption_algorithm TEXT NOT NULL DEFAULT 'AES-256-GCM',
                masked_hint TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                last_validated_at TIMESTAMPTZ,
                last_error_code TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                activated_at TIMESTAMPTZ,
                retired_at TIMESTAMPTZ,
                CHECK (purpose = 'llm'),
                CHECK (provider IN (
                    'openai','groq','openrouter','gemini','ollama_cloud'
                )),
                CHECK (status IN ('pending','active','invalid','retired'))
            )
            """
        )
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS user_llm_credentials_one_active
            ON user_llm_credentials (user_id) WHERE status = 'active'
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS user_llm_credentials_user_created
            ON user_llm_credentials (user_id, created_at DESC)
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_llm_audit_events (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                provider TEXT,
                result TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

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
    ) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                INSERT INTO user_llm_credentials (
                    id, user_id, provider, purpose, model, ciphertext, nonce,
                    masked_hint, fingerprint, status
                ) VALUES ($1,$2,$3,'llm',$4,$5,$6,$7,$8,'pending')
                """,
                uuid.UUID(credential_id),
                uuid.UUID(user_id),
                provider,
                model,
                ciphertext,
                nonce,
                masked_hint,
                fingerprint,
            )
        finally:
            await connection.close()

    async def activate(self, credential_id: str, user_id: str) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            async with connection.transaction():
                pending = await connection.fetchval(
                    """
                    SELECT id FROM user_llm_credentials
                    WHERE id=$1 AND user_id=$2 AND status='pending'
                    FOR UPDATE
                    """,
                    uuid.UUID(credential_id),
                    uuid.UUID(user_id),
                )
                if pending is None:
                    raise RuntimeError("pending_user_llm_credential_not_found")
                await connection.execute(
                    """
                    UPDATE user_llm_credentials
                    SET status='retired', retired_at=NOW()
                    WHERE user_id=$1 AND status='active'
                    """,
                    uuid.UUID(user_id),
                )
                await connection.execute(
                    """
                    UPDATE user_llm_credentials
                    SET status='active', activated_at=NOW(),
                        last_validated_at=NOW(), last_error_code=NULL
                    WHERE id=$1 AND user_id=$2 AND status='pending'
                    """,
                    uuid.UUID(credential_id),
                    uuid.UUID(user_id),
                )
        finally:
            await connection.close()

    async def mark_invalid(
        self, credential_id: str, user_id: str, error_code: str
    ) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                UPDATE user_llm_credentials
                SET status='invalid', last_validated_at=NOW(), last_error_code=$3
                WHERE id=$1 AND user_id=$2 AND status='pending'
                """,
                uuid.UUID(credential_id),
                uuid.UUID(user_id),
                error_code,
            )
        finally:
            await connection.close()

    async def active_metadata(self, user_id: str) -> dict[str, Any] | None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                """
                SELECT provider, model, status, masked_hint, last_validated_at,
                       last_error_code, activated_at
                FROM user_llm_credentials
                WHERE user_id=$1 AND status='active'
                """,
                uuid.UUID(user_id),
            )
            return dict(row) if row is not None else None
        finally:
            await connection.close()

    async def retire_active(self, user_id: str) -> bool:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            result = await connection.execute(
                """
                UPDATE user_llm_credentials
                SET status='retired', retired_at=NOW()
                WHERE user_id=$1 AND status='active'
                """,
                uuid.UUID(user_id),
            )
            return result != "UPDATE 0"
        finally:
            await connection.close()

    async def append_audit(
        self,
        user_id: str,
        action: str,
        provider: str | None,
        result: str,
        correlation_id: str,
    ) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """
                INSERT INTO user_llm_audit_events (
                    id, user_id, action, provider, result, correlation_id
                ) VALUES ($1,$2,$3,$4,$5,$6)
                """,
                uuid.uuid4(),
                uuid.UUID(user_id),
                action,
                provider,
                result,
                correlation_id,
            )
        finally:
            await connection.close()
