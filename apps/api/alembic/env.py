"""Alembic env for unifi-api.

The DB file is unencrypted at the engine layer (sensitive columns use
AES-GCM at the application layer per unifi_api.db.crypto). The DB path is
resolvable from config or via -x db_path=... on the alembic command line.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

# Make unifi_api importable when alembic runs standalone
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from unifi_api.db.engine import create_engine  # noqa: E402
from unifi_api.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def _resolve_db_path() -> Path:
    cli_args = context.get_x_argument(as_dictionary=True)
    if "db_path" in cli_args:
        return Path(cli_args["db_path"])
    env_path = os.environ.get("UNIFI_API_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path("./state.db")


def run_migrations_offline() -> None:
    raise RuntimeError("Offline migration mode is not supported; the async engine requires a live connection.")


async def run_migrations_online() -> None:
    engine: AsyncEngine = create_engine(_resolve_db_path())
    async with engine.connect() as conn:
        await conn.run_sync(_run_sync_migrations)
    await engine.dispose()


def _run_sync_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
