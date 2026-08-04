"""JWT authentication HTTP routes."""

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth_dependencies import require_user_id
from app.infrastructure.auth_service import JwtService, PasswordService
from app.infrastructure.user_repository import UserAlreadyExists, UserRepository


class Credentials(BaseModel):
    email: str
    password: str


def create_auth_router(users: UserRepository, jwt_service: JwtService) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    @router.post("/signup")
    async def signup(credentials: Credentials) -> JSONResponse:
        if len(credentials.password) < 8:
            return JSONResponse({"error": "password_too_short"}, status_code=400)
        try:
            user_id = await users.create(
                credentials.email, PasswordService.hash(credentials.password)
            )
        except UserAlreadyExists:
            return JSONResponse({"error": "email_already_registered"}, status_code=409)
        except Exception:
            return JSONResponse({"error": "database_unavailable"}, status_code=503)
        return JSONResponse(
            {
                "userId": user_id,
                "role": "user",
                "accessToken": jwt_service.issue_access_token(user_id),
            },
            status_code=201,
        )

    @router.post("/login")
    async def login(credentials: Credentials) -> JSONResponse:
        try:
            user = await users.find_by_email(credentials.email)
        except Exception:
            return JSONResponse({"error": "database_unavailable"}, status_code=503)
        if user is None or not PasswordService.verify(
            credentials.password, str(user["password_hash"])
        ):
            return JSONResponse({"error": "invalid_credentials"}, status_code=401)
        user_id = str(user["id"])
        await users.record_login(user_id)
        return JSONResponse(
            {
                "userId": user_id,
                "role": str(user["role"]),
                "accessToken": jwt_service.issue_access_token(user_id),
            }
        )

    @router.get("/me")
    async def me(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        try:
            user_id = require_user_id(authorization, jwt_service)
            user = await users.find_by_id(user_id)
        except Exception:
            return JSONResponse({"error": "invalid_access_token"}, status_code=401)
        if user is None:
            return JSONResponse({"error": "invalid_access_token"}, status_code=401)
        return JSONResponse({"userId": user_id, "role": str(user["role"])})

    return router
