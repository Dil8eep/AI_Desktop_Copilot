"""Authenticated per-user LLM configuration routes."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr

from app.api.auth_dependencies import require_user_id
from app.application.user_llm_credential_service import UserLlmCredentialService
from app.infrastructure.auth_service import JwtService


class UserLlmCredentialOperation(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=200)
    credential: SecretStr = Field(min_length=1, json_schema_extra={"writeOnly": True})


def _disable_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, object]:
    validated_at = metadata.get("last_validated_at")
    return {
        "configured": True,
        "provider": str(metadata["provider"]),
        "model": str(metadata["model"]),
        "status": str(metadata["status"]),
        "maskedHint": str(metadata["masked_hint"]),
        "lastValidatedAt": (
            validated_at.isoformat()
            if isinstance(validated_at, datetime)
            else validated_at
        ),
    }


def create_user_llm_router(
    jwt_service: JwtService,
    credential_service: UserLlmCredentialService | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/llm/config")

    def require_service() -> UserLlmCredentialService:
        if credential_service is None:
            raise HTTPException(
                status_code=503, detail="credential_master_key_not_configured"
            )
        return credential_service

    @router.get("")
    async def get_config(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        user_id = require_user_id(authorization, jwt_service)
        metadata = await require_service().metadata(user_id)
        _disable_caching(response)
        if metadata is None:
            return {"configured": False}
        return _safe_metadata(metadata)

    @router.post("/validate")
    async def validate_config(
        operation: UserLlmCredentialOperation,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_user_id(authorization, jwt_service)
        service = require_service()
        try:
            validation = await service.validate_only(
                operation.provider,
                operation.credential.get_secret_value(),
                operation.model,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        _disable_caching(response)
        return {
            "provider": operation.provider.strip().lower(),
            "model": operation.model.strip(),
            "valid": validation.valid,
            "errorCode": validation.error_code,
        }

    @router.put("")
    async def replace_config(
        operation: UserLlmCredentialOperation,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        user_id = require_user_id(authorization, jwt_service)
        service = require_service()
        try:
            result = await service.replace(
                user_id,
                operation.provider,
                operation.credential.get_secret_value(),
                operation.model,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
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
            "configured": True,
            "provider": result.provider,
            "model": result.model,
            "status": result.status,
            "maskedHint": result.masked_hint,
            "correlationId": result.correlation_id,
        }

    @router.delete("")
    async def remove_config(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        user_id = require_user_id(authorization, jwt_service)
        removed = await require_service().remove(user_id)
        _disable_caching(response)
        return {"configured": False, "removed": removed}

    return router
