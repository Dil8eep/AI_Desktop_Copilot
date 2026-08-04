"""HTTP-level regressions for the read-only administrator portal."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.admin import create_admin_router
from app.api.auth import create_auth_router
from app.infrastructure.auth_service import JwtService
from app.settings import Settings


class FakeUsers:
    def __init__(self, role: str = "user") -> None:
        self.role = role
        self.created_email: str | None = None

    async def create(self, email: str, password_hash: str) -> str:
        self.created_email = email
        assert password_hash
        return "new-user"

    async def find_by_id(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "role": self.role}

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        return None

    async def record_login(self, user_id: str) -> None:
        return None

    async def password_hash_for_user(self, user_id: str) -> str | None:
        return None


class FakeAdminRepository:
    async def overview(self, period_days: int) -> dict[str, int]:
        assert period_days == 7
        return {
            "total_users": 12,
            "new_users": 3,
            "recently_active": 5,
            "users_with_profiles": 8,
        }

    async def list_users(
        self, query: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        return ([{"id": "u1", "email": "person@example.com", "role": "user"}], 1)

    async def list_audit_events(
        self, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        return ([], 0)


def admin_app(
    role: str, settings: Settings | None = None
) -> tuple[FastAPI, JwtService]:
    jwt_service = JwtService("test-secret-that-is-at-least-32-bytes", 15)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            FakeUsers(role),
            jwt_service,
            FakeAdminRepository(),
            settings or Settings(llm_provider="mock", speech_provider="mock"),
        )
    )
    return app, jwt_service


def test_admin_access_endpoint_rejects_regular_user() -> None:
    app, jwt_service = admin_app("user")
    token = jwt_service.issue_access_token("regular-user")

    response = TestClient(app).get(
        "/api/admin/access", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "admin_required"}


def test_overview_is_admin_only_and_not_cacheable() -> None:
    app, jwt_service = admin_app("admin")
    token = jwt_service.issue_access_token("admin-user")

    response = TestClient(app).get(
        "/api/admin/overview", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["metrics"]["total_users"] == 12


def test_provider_response_contains_metadata_but_no_secret() -> None:
    settings = Settings(
        llm_provider="openai",
        speech_provider="groq",
        openai_api_key=SecretStr("private-openai-key"),
        groq_api_key=SecretStr("private-groq-key"),
    )
    app, jwt_service = admin_app("admin", settings)
    token = jwt_service.issue_access_token("admin-user")

    response = TestClient(app).get(
        "/api/admin/providers", headers={"Authorization": f"Bearer {token}"}
    )

    body = response.text
    assert response.status_code == 200
    assert "private-openai-key" not in body
    assert "private-groq-key" not in body
    assert "ciphertext" not in body
    assert response.json()["providers"][0]["status"] == "configured"


def test_public_signup_always_returns_user_role() -> None:
    jwt_service = JwtService("test-secret-that-is-at-least-32-bytes", 15)
    users = FakeUsers("admin")
    app = FastAPI()
    app.include_router(create_auth_router(users, jwt_service))  # type: ignore[arg-type]

    response = TestClient(app).post(
        "/api/auth/signup",
        json={"email": "candidate@example.com", "password": "strong-pass"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "user"
    assert users.created_email == "candidate@example.com"
