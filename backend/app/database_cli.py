"""Database deployment commands."""

import argparse
import asyncio

from app.infrastructure.schema_manager import SchemaManager
from app.settings import Settings


async def _migrate() -> None:
    await SchemaManager(Settings().database_url).migrate()
    print("database_migrations_complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["migrate"])
    parser.parse_args()
    asyncio.run(_migrate())


if __name__ == "__main__":
    main()
