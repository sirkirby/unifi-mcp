"""Add the singleton cloud connection and independent audit identity."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sitemanager_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("singleton_slot", sa.Integer, nullable=False, server_default="1", unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("api_key_blob", sa.LargeBinary, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_slot = 1", name="ck_sitemanager_singleton"),
        sa.CheckConstraint("revision >= 1", name="ck_sitemanager_revision"),
    )
    op.add_column("audit_log", sa.Column("sitemanager_connection", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "sitemanager_connection")
    op.drop_table("sitemanager_connections")
