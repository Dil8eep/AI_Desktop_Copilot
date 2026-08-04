"""Authorization tests for the database-authoritative administrator boundary."""

from typing import Any

import pytest
from fastapi import HTTPException

from app.api.auth_dependencies import require_admin_id
from app.infrastructure.auth_service import JwtService


class FakeUsers:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def find_by_id(self, user_id: str) -> dict[str, Any] | None:
        if self.role is None:
            return None
        return {"id": user_id, "role": self.role}


@pytest.fixture
def jwt_service() -> JwtService:
    return JwtService("test-secret-with-enough-entropy", 15)


@pytest.mark.asyncio
async def test_regular_user_is_forbidden_from_admin_boundary(
    jwt_service: JwtService,
) -> None:
    token = jwt_service.issue_access_token("regular-user")

    with pytest.raises(HTTPException) as raised:
        await require_admin_id(f"Bearer {token}", jwt_service, FakeUsers("user"))

    assert raised.value.status_code == 403
    assert raised.value.detail == "admin_required"


@pytest.mark.asyncio
async def test_admin_role_is_read_from_database(jwt_service: JwtService) -> None:
    token = jwt_service.issue_access_token("admin-user")

    user_id = await require_admin_id(f"Bearer {token}", jwt_service, FakeUsers("admin"))

    assert user_id == "admin-user"


@pytest.mark.asyncio
async def test_deleted_user_is_forbidden(jwt_service: JwtService) -> None:
    token = jwt_service.issue_access_token("deleted-user")

    with pytest.raises(HTTPException) as raised:
        await require_admin_id(f"Bearer {token}", jwt_service, FakeUsers(None))

    assert raised.value.status_code == 403
