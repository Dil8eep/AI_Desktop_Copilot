
"""Controlled command for provisioning the first administrator."""

import argparse
import asyncio
from typing import Protocol

from app.infrastructure.user_repository import UserRepository
from app.settings import Settings


class AdminPromoter(Protocol):
    async def promote_to_admin(self, email: str) -> bool: ...


async def provision_bootstrap_admin(
    settings: Settings, promoter: AdminPromoter
) -> bool:
    """Promote an existing account named only in backend configuration."""
    email = settings.bootstrap_admin_email
    if not email:
        raise ValueError("COPILOT_BOOTSTRAP_ADMIN_EMAIL is required")
    return await promoter.promote_to_admin(email)


async def _run() -> int:
    settings = Settings()
    repository = UserRepository(settings.database_url)
    promoted = await provision_bootstrap_admin(settings, repository)
    if not promoted:
        print("bootstrap_admin_user_not_found")
        return 1
    print("bootstrap_admin_promoted")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["promote-bootstrap-admin"])
    parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_run()))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
