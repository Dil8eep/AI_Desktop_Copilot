"""FastAPI dependencies for validating JWT users and administrator roles."""

from typing import Any, Protocol

from fastapi import HTTPException

from app.infrastructure.auth_service import JwtService


class UserRoleLookup(Protocol):
    async def find_by_id(self, user_id: str) -> dict[str, Any] | None: ...


def require_user_id(authorization: str | None, jwt_service: JwtService) -> str:
    """Validate an Authorization header and return the authenticated user ID."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    try:
        return jwt_service.verify_access_token(authorization[7:])
    except Exception as error:
        raise HTTPException(status_code=401, detail="invalid_access_token") from error


async def require_admin_id(
    authorization: str | None,
    jwt_service: JwtService,
    users: UserRoleLookup,
) -> str:
    """Require a current database role of admin; JWT claims are not authoritative."""
    user_id = require_user_id(authorization, jwt_service)
    user = await users.find_by_id(user_id)
    if user is None or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return user_id
