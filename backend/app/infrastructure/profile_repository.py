"""Async PostgreSQL repository for authenticated candidate profiles."""

import json
from typing import Any
from uuid import UUID


class ProfileRepository:
    """Stores one candidate profile per authenticated user."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    async def save(self, user_id: str, profile: dict[str, Any]) -> None:
        """Create or replace the authenticated user's parsed profile."""

        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._database_url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                """INSERT INTO candidate_profiles_by_user (user_id, profile)
                   VALUES ($1, $2::jsonb)
                   ON CONFLICT (user_id) DO UPDATE SET
                     profile = EXCLUDED.profile,
                     updated_at = NOW()""",
                UUID(user_id),
                json.dumps(profile),
            )
        finally:
            await connection.close()

    async def get(self, user_id: str) -> dict[str, Any] | None:
        """Return only the profile belonging to the authenticated user."""

        import asyncpg

        connection = await asyncpg.connect(self._database_url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                """SELECT profile FROM candidate_profiles_by_user
                   WHERE user_id = $1""",
                UUID(user_id),
            )
            if row is None:
                return None
            value = row["profile"]
            return value if isinstance(value, dict) else json.loads(value)
        finally:
            await connection.close()

    @staticmethod
    async def _ensure_schema(connection: Any) -> None:
        await connection.execute(
            """CREATE TABLE IF NOT EXISTS candidate_profiles_by_user (
                user_id UUID PRIMARY KEY,
                profile JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )
