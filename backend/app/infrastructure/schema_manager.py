"""Idempotent PostgreSQL schema migration coordinator."""

from app.infrastructure.admin_repository import AdminRepository
from app.infrastructure.profile_repository import ProfileRepository
from app.infrastructure.provider_credential_repository import (
    ProviderCredentialRepository,
)
from app.infrastructure.user_repository import UserRepository


class SchemaManager:
    def __init__(self, database_url: str) -> None:
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    async def migrate(self) -> None:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(self._url)
        try:
            async with connection.transaction():
                await UserRepository._ensure_schema(connection)
                await ProfileRepository._ensure_schema(connection)
                await AdminRepository._ensure_schema(connection)
                await ProviderCredentialRepository._ensure_schema(connection)
                await self._protect_audit_events(connection)
        finally:
            await connection.close()

    @staticmethod
    async def _protect_audit_events(connection: object) -> None:
        await connection.execute(  # type: ignore[attr-defined]
            """
            CREATE OR REPLACE FUNCTION prevent_admin_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'admin_audit_events_are_append_only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        await connection.execute(  # type: ignore[attr-defined]
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'admin_audit_events_append_only'
                ) THEN
                    CREATE TRIGGER admin_audit_events_append_only
                    BEFORE UPDATE OR DELETE ON admin_audit_events
                    FOR EACH ROW EXECUTE FUNCTION prevent_admin_audit_mutation();
                END IF;
            END $$
            """
        )
