"""add app_settings table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-30
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    defaults = [
        ("audit.retention.max_age_days", "90"),
        ("audit.retention.max_rows", "1000000"),
        ("audit.retention.enabled", "true"),
        ("audit.retention.prune_interval_hours", "6"),
        ("logs.file.enabled", "true"),
        ("logs.file.path", "state/api.log"),
        ("logs.file.max_bytes", "10485760"),
        ("logs.file.backup_count", "5"),
        ("logs.file.level", "INFO"),
        ("theme.default", "auto"),
    ]
    op.bulk_insert(
        sa.table(
            "app_settings",
            sa.column("key", sa.String),
            sa.column("value", sa.Text),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [{"key": k, "value": v, "updated_at": datetime.now(timezone.utc)} for k, v in defaults],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
