"""HTTP security checks for write-only provider credential operations."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import create_admin_router
from app.application.provider_credential_service import ProviderCredentialService
from app.infrastructure.auth_service import JwtService, PasswordService
from app.infrastructure.credential_cipher import CredentialCipher
from app.infrastructure.provider_credential_validator import CredentialValidation
from app.settings import Settings


class AdminUsers:
    def __init__(self) -> None:
        self.password_hash = PasswordService.hash("test-admin-password")

    async def find_by_id(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "role": "admin"}

    async def password_hash_for_user(self, user_id: str) -> str:
        return self.password_hash


class ReadRepository:
    async def overview(self, period_days: int) -> dict[str, int]:
        return {}

    async def list_users(
        self, query: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        return [], 0

    async def list_audit_events(
        self, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        return [], 0


class CredentialRepository:
    def __init__(self) -> None:
        self.activated = False

    async def create_pending(self, *args: Any) -> None:
        return None

    async def activate(self, credential_id: str, provider: str) -> None:
        self.activated = True

    async def mark_invalid(self, credential_id: str, error_code: str) -> None:
        return None

    async def active_metadata(self) -> list[dict[str, Any]]:
        return []

    async def append_audit(self, *args: Any) -> None:
        return None


class Validator:
    def __init__(self, valid: bool) -> None:
        self.valid = valid
        self.received: str | None = None

    async def validate(
        self, provider: str, credential: str, model: str | None = None
    ) -> CredentialValidation:
        self.received = credential
        return CredentialValidation(
            self.valid,
            None if self.valid else "provider_authentication_failed",
        )


def build_client(
    validator: Validator,
) -> tuple[TestClient, JwtService, CredentialRepository]:
    jwt_service = JwtService("test-secret-that-is-at-least-32-bytes", 15)
    credentials = CredentialRepository()
    service = ProviderCredentialService(
        credentials,
        validator,
        CredentialCipher(CredentialCipher.generate_master_key()),
    )
    app = FastAPI()
    app.include_router(
        create_admin_router(
            AdminUsers(),
            jwt_service,
            ReadRepository(),
            Settings(llm_provider="mock", speech_provider="mock"),
            service,
        )
    )
    return TestClient(app), jwt_service, credentials


def test_validation_accepts_model_and_key_without_password() -> None:
    validator = Validator(True)
    client, jwt_service, _ = build_client(validator)
    token = jwt_service.issue_access_token("admin-user")

    response = client.post(
        "/api/admin/providers/openai/validate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credential": "test-provider-credential-value",
            "model": "gpt-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert validator.received == "test-provider-credential-value"


def test_replacement_response_never_contains_submitted_secrets() -> None:
    validator = Validator(True)
    client, jwt_service, credentials = build_client(validator)
    token = jwt_service.issue_access_token("admin-user")

    response = client.put(
        "/api/admin/providers/openai/credential",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credential": "test-provider-credential-value",
            "currentPassword": "test-admin-password",
            "model": "gpt-test",
        },
    )

    assert response.status_code == 200
    assert credentials.activated is True
    assert "test-provider-credential-value" not in response.text
    assert "test-admin-password" not in response.text
    assert response.json()["maskedHint"] == "...alue"
