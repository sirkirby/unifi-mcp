"""Async SQLAlchemy engine backed by plain SQLite via aiosqlite.

Encryption of sensitive columns is handled at the application layer via
unifi_api.db.crypto.ColumnCipher — see crypto.py and the controllers manager
(Phase 2) for usage. The DB file itself is unencrypted.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(db_path: Path | str) -> AsyncEngine:
    """Create an async engine pointing at a SQLite file.

    Parent directories are created if missing. The DB file is unencrypted;
    sensitive columns use AES-GCM via `ColumnCipher` at the application layer.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve literal filesystem characters instead of parsing them as URL escapes.
    url = URL.create("sqlite+aiosqlite", database=str(db_path))
    return create_async_engine(
        url,
        connect_args={"check_same_thread": False},
        future=True,
    )
