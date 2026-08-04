"""PostgreSQL user repository for JWT authentication and admin roles."""

import uuid
from typing import Any


class UserAlreadyExists(Exception):
    """Raised when an email is already registered."""


class UserRepository:
    """Persist users while keeping role checks authoritative in PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    @staticmethod
    async def _ensure_schema(connection: Any) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            )
            """
        )
        await connection.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role "
            "TEXT NOT NULL DEFAULT 'user'"
        )
        await connection.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"
        )

    async def ensure_schema(self) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
        finally:
            await connection.close()

    async def create(self, email: str, password_hash: str) -> str:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            user_id = str(uuid.uuid4())
            try:
                await connection.execute(
                    "INSERT INTO users (id,email,password_hash,role) "
                    "VALUES ($1,$2,$3,'user')",
                    user_id,
                    email.lower(),
                    password_hash,
                )
            except asyncpg.UniqueViolationError as error:
                raise UserAlreadyExists from error
            return user_id
        finally:
            await connection.close()

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                "SELECT id::text,email,password_hash,role,created_at,last_login_at "
                "FROM users WHERE email=$1",
                email.lower(),
            )
            return dict(row) if row else None
        finally:
            await connection.close()

    async def find_by_id(self, user_id: str) -> dict[str, Any] | None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            row = await connection.fetchrow(
                "SELECT id::text,email,role,created_at,last_login_at "
                "FROM users WHERE id=$1",
                user_id,
            )
            return dict(row) if row else None
        finally:
            await connection.close()

    async def password_hash_for_user(self, user_id: str) -> str | None:
        """Return a password hash only for internal recent-auth verification."""
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            value = await connection.fetchval(
                "SELECT password_hash FROM users WHERE id=$1", user_id
            )
            return str(value) if value is not None else None
        finally:
            await connection.close()

    async def record_login(self, user_id: str) -> None:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            await connection.execute(
                "UPDATE users SET last_login_at=NOW() WHERE id=$1", user_id
            )
        finally:
            await connection.close()

    async def promote_to_admin(self, email: str) -> bool:
        import asyncpg

        connection = await asyncpg.connect(self._url)
        try:
            await self._ensure_schema(connection)
            result = await connection.execute(
                "UPDATE users SET role='admin' WHERE email=$1", email.lower()
            )
            return str(result) == "UPDATE 1"
        finally:
            await connection.close()
