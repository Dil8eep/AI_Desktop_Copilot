"""Administrator portal routes, including write-only credential operations."""

from typing import Any, Protocol

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, SecretStr

from app.api.auth_dependencies import UserRoleLookup, require_admin_id
from app.application.provider_credential_service import ProviderCredentialService
from app.infrastructure.auth_service import JwtService
from app.settings import Settings


class AdminUserLookup(UserRoleLookup, Protocol):
    async def password_hash_for_user(self, user_id: str) -> str | None: ...


class AdminReadRepository(Protocol):
    async def overview(self, period_days: int) -> dict[str, int]: ...

    async def list_users(
        self, query: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def list_audit_events(
        self, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]: ...


class CredentialOperation(BaseModel):
    credential: SecretStr = Field(
        min_length=8, max_length=512, json_schema_extra={"writeOnly": True}
    )
    model: str | None = Field(default=None, min_length=1, max_length=120)


def _disable_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _environment_provider_metadata(settings: Settings) -> list[dict[str, object]]:
    return [
        {
            "provider": "openai",
            "purpose": "llm",
            "model": settings.openai_model,
            "status": (
                "configured" if settings.openai_api_key is not None else "missing"
            ),
            "maskedHint": None,
            "source": "environment",
            "lastValidatedAt": None,
            "lastErrorCode": None,
            "canRollback": False,
        },
        {
            "provider": "groq",
            "purpose": "stt",
            "model": settings.groq_whisper_model,
            "status": "configured" if settings.groq_api_key is not None else "missing",
            "maskedHint": None,
            "source": "environment",
            "lastValidatedAt": None,
            "lastErrorCode": None,
            "canRollback": False,
        },
    ]


def create_admin_router(
    users: AdminUserLookup,
    jwt_service: JwtService,
    repository: AdminReadRepository,
    settings: Settings,
    credential_service: ProviderCredentialService | None = None,
) -> APIRouter:
    """Create database-authorized admin APIs with write-only secret inputs."""
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/access")
    async def verify_admin_access(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        user_id = await require_admin_id(authorization, jwt_service, users)
        _disable_caching(response)
        return {"userId": user_id, "role": "admin"}

    @router.get("/overview")
    async def overview(
        response: Response,
        authorization: str | None = Header(default=None),
        period_days: int = Query(default=7, alias="periodDays", ge=1, le=90),
    ) -> dict[str, object]:
        await require_admin_id(authorization, jwt_service, users)
        metrics = await repository.overview(period_days)
        _disable_caching(response)
        return {"periodDays": period_days, "metrics": metrics}

    @router.get("/users")
    async def list_users(
        response: Response,
        authorization: str | None = Header(default=None),
        query: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    ) -> dict[str, object]:
        await require_admin_id(authorization, jwt_service, users)
        records, total = await repository.list_users(query, page, page_size)
        _disable_caching(response)
        return {
            "users": records,
            "pagination": {"page": page, "pageSize": page_size, "total": total},
        }

    @router.get("/providers")
    async def providers(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_admin_id(authorization, jwt_service, users)
        metadata = _environment_provider_metadata(settings)
        for item in metadata:
            item["managementAvailable"] = credential_service is not None
        if credential_service is not None:
            managed = await credential_service.active_metadata()
            managed_by_provider = {str(item["provider"]): item for item in managed}
            for item in metadata:
                active = managed_by_provider.get(str(item["provider"]))
                if active is None:
                    continue
                item.update(
                    {
                        "model": active.get("model"),
                        "status": active.get("status"),
                        "maskedHint": active.get("masked_hint"),
                        "source": "managed",
                        "lastValidatedAt": active.get("last_validated_at"),
                        "lastErrorCode": active.get("last_error_code"),
                        "canRollback": bool(active.get("can_rollback")),
                    }
                )
        _disable_caching(response)
        return {"providers": metadata}

    @router.post("/providers/{provider}/validate")
    async def validate_provider_credential(
        provider: str,
        operation: CredentialOperation,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_admin_id(authorization, jwt_service, users)
        if credential_service is None:
            raise HTTPException(
                status_code=503, detail="credential_master_key_not_configured"
            )
        try:
            validation = await credential_service.validate_only(
                provider,
                operation.credential.get_secret_value(),
                operation.model,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        _disable_caching(response)
        return {
            "provider": provider,
            "valid": validation.valid,
            "errorCode": validation.error_code,
        }

    @router.put("/providers/{provider}/credential")
    async def replace_provider_credential(
        provider: str,
        operation: CredentialOperation,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        admin_id = await require_admin_id(authorization, jwt_service, users)
        if credential_service is None:
            raise HTTPException(
                status_code=503, detail="credential_master_key_not_configured"
            )
        try:
            result = await credential_service.replace(
                provider,
                operation.credential.get_secret_value(),
                operation.model,
                admin_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        _disable_caching(response)
        if not result.activated:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": result.error_code,
                    "correlationId": result.correlation_id,
                },
            )
        return {
            "provider": result.provider,
            "purpose": result.purpose,
            "model": result.model,
            "status": result.status,
            "maskedHint": result.masked_hint,
            "correlationId": result.correlation_id,
        }

    @router.post("/providers/{provider}/rollback")
    async def rollback_provider_credential(
        provider: str,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        admin_id = await require_admin_id(authorization, jwt_service, users)
        if credential_service is None:
            raise HTTPException(
                status_code=503, detail="credential_master_key_not_configured"
            )
        try:
            result = await credential_service.rollback(provider, admin_id)
        except ValueError as error:
            status = 404 if str(error) == "rollback_credential_not_found" else 422
            raise HTTPException(status_code=status, detail=str(error)) from error
        _disable_caching(response)
        if not result.activated:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": result.error_code,
                    "correlationId": result.correlation_id,
                },
            )
        return {
            "provider": result.provider,
            "purpose": result.purpose,
            "model": result.model,
            "status": result.status,
            "maskedHint": result.masked_hint,
            "correlationId": result.correlation_id,
        }

    @router.get("/audit-events")
    async def audit_events(
        response: Response,
        authorization: str | None = Header(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    ) -> dict[str, object]:
        await require_admin_id(authorization, jwt_service, users)
        events, total = await repository.list_audit_events(page, page_size)
        _disable_caching(response)
        return {
            "events": events,
            "pagination": {"page": page, "pageSize": page_size, "total": total},
        }

    return router
