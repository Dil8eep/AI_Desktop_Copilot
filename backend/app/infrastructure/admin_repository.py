"""Read-only PostgreSQL queries for the administrator portal."""

from typing import Any


class AdminRepository:
    """Expose operational metadata without returning private user content."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    @staticmethod
    async def _ensure_schema(connection: Any) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_profiles_by_user (
                user_id UUID PRIMARY KEY,
                profile JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
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

    async def ping(self) -> bool:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            return bool(await connection.fetchval("SELECT TRUE"))
        finally:
            await connection.close()

    async def overview(self, period_days: int) -> dict[str, int]:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                """
                SELECT
                    COUNT(*)::int AS total_users,
                    COUNT(*) FILTER (
                        WHERE created_at >= NOW() - ($1 * INTERVAL '1 day')
                    )::int AS new_users,
                    COUNT(*) FILTER (
                        WHERE last_login_at >= NOW() - ($1 * INTERVAL '1 day')
                    )::int AS recently_active,
                    COUNT(p.user_id)::int AS users_with_profiles
                FROM users u
                LEFT JOIN candidate_profiles_by_user p ON p.user_id = u.id
                """,
                period_days,
            )
            return dict(row)
        finally:
            await connection.close()

    async def list_users(
        self, query: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            search = f"%{query.strip()}%"
            total = await connection.fetchval(
                "SELECT COUNT(*)::int FROM users WHERE email ILIKE $1", search
            )
            rows = await connection.fetch(
                """
                SELECT u.id::text, u.email, u.role, u.created_at, u.last_login_at,
                       (p.user_id IS NOT NULL) AS profile_ready
                FROM users u
                LEFT JOIN candidate_profiles_by_user p ON p.user_id = u.id
                WHERE u.email ILIKE $1
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT $2 OFFSET $3
                """,
                search,
                page_size,
                (page - 1) * page_size,
            )
            return [dict(row) for row in rows], int(total or 0)
        finally:
            await connection.close()

    async def list_audit_events(
        self, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            total = await connection.fetchval(
                "SELECT COUNT(*)::int FROM admin_audit_events"
            )
            rows = await connection.fetch(
                """
                SELECT e.id::text, e.actor_user_id::text, u.email AS actor_email,
                       e.action, e.target_type, e.target_id, e.result,
                       e.correlation_id, e.created_at
                FROM admin_audit_events e
                LEFT JOIN users u ON u.id = e.actor_user_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT $1 OFFSET $2
                """,
                page_size,
                (page - 1) * page_size,
            )
            return [dict(row) for row in rows], int(total or 0)
        finally:
            await connection.close()
