"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prefix", sa.String(64), nullable=False, unique=True),
        sa.Column("hash", sa.String(255), nullable=False),
        sa.Column("scopes", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "controllers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("product_kinds", sa.String(64), nullable=False),
        sa.Column("credentials_blob", sa.LargeBinary, nullable=False),
        sa.Column("verify_tls", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("api_key_id", sa.String(36), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_id_prefix", sa.String(64), nullable=False),
        sa.Column("controller", sa.String(36), nullable=True),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("error_kind", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("sessions")
    op.drop_table("controllers")
    op.drop_table("api_keys")
    op.drop_table("schema_version")
