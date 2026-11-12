"""SQLAlchemy 2.0 declarative models for the unifi-api state database.

Skeleton models for Phase 1 — fields evolve in later phases. All tables
documented in the spec §6.1, §7.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Controller(Base):
    __tablename__ = "controllers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    product_kinds: Mapped[str] = mapped_column(String(64), nullable=False)
    credentials_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SiteManagerConnection(Base):
    """One account-level cloud connection, separate from local consoles."""

    __tablename__ = "sitemanager_connections"
    __table_args__ = (
        CheckConstraint("singleton_slot = 1", name="ck_sitemanager_singleton"),
        CheckConstraint("revision >= 1", name="ck_sitemanager_revision"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    singleton_slot: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    api_key_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_keys.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    key_id_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    controller: Mapped[Optional[str]] = mapped_column(String(36))
    sitemanager_connection: Mapped[Optional[str]] = mapped_column(String(36))
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_kind: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)


class AppSetting(Base):
    """Single-row-per-setting key/value store for runtime configuration."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
