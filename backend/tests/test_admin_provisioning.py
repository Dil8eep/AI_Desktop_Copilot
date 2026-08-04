"""Tests for controlled first-administrator provisioning."""

import pytest

from app.admin_cli import provision_bootstrap_admin
from app.settings import Settings


class FakePromoter:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.email: str | None = None

    async def promote_to_admin(self, email: str) -> bool:
        self.email = email
        return self.result


@pytest.mark.asyncio
async def test_bootstrap_admin_uses_backend_only_configured_identity() -> None:
    settings = Settings(bootstrap_admin_email="owner@example.com")
    promoter = FakePromoter()

    assert await provision_bootstrap_admin(settings, promoter) is True
    assert promoter.email == "owner@example.com"


@pytest.mark.asyncio
async def test_bootstrap_admin_requires_explicit_identity() -> None:
    settings = Settings(bootstrap_admin_email=None)

    with pytest.raises(ValueError, match="COPILOT_BOOTSTRAP_ADMIN_EMAIL"):
        await provision_bootstrap_admin(settings, FakePromoter())
