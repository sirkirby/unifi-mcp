"""Singleton cloud account storage. Callers own transactions; outputs omit credentials."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

from unifi_api.db.crypto import ColumnCipher
from unifi_api.db.models import SiteManagerConnection


class SiteManagerConnectionNotFound(Exception):
    pass


class SiteManagerConnectionConflict(Exception):
    pass


class SiteManagerConfigurationError(Exception):
    pass


def associated_data(connection_id: str) -> bytes:
    return b"unifi-api:sitemanager:" + connection_id.encode()


def metadata(row: SiteManagerConnection) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "key_configured": True,
        "revision": row.revision,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def list_connections(session: AsyncSession) -> list[SiteManagerConnection]:
    return list((await session.scalars(select(SiteManagerConnection))).all())


async def get_connection(session: AsyncSession) -> SiteManagerConnection:
    row = (await session.scalars(select(SiteManagerConnection))).one_or_none()
    if row is None:
        raise SiteManagerConnectionNotFound("Site Manager connection is not configured")
    return row


async def create_connection(
    session: AsyncSession, cipher: ColumnCipher, payload: SiteManagerConnectionCreate
) -> SiteManagerConnection:
    connection_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    row = SiteManagerConnection(
        id=connection_id,
        name=payload.name,
        api_key_blob=cipher.encrypt(
            payload.site_manager_api_key.get_secret_value().encode(), associated_data=associated_data(connection_id)
        ),
        revision=1,
        created_at=now,
        updated_at=now,
    )
    # A savepoint keeps the caller transaction usable after a singleton conflict.
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError as exc:
        if "UNIQUE constraint failed: sitemanager_connections.singleton_slot" in str(exc.orig):
            raise SiteManagerConnectionConflict("Site Manager connection is already configured") from None
        raise
    return row


async def update_connection(
    session: AsyncSession, cipher: ColumnCipher, payload: SiteManagerConnectionPatch
) -> SiteManagerConnection:
    row = await get_connection(session)
    changes = {}
    if "name" in payload.model_fields_set and payload.name != row.name:
        changes["name"] = payload.name
    if "site_manager_api_key" in payload.model_fields_set:
        changes["api_key_blob"] = cipher.encrypt(
            payload.site_manager_api_key.get_secret_value().encode(), associated_data=associated_data(row.id)
        )
    if changes:
        changes.update(revision=SiteManagerConnection.revision + 1, updated_at=datetime.now(timezone.utc))
        await session.execute(update(SiteManagerConnection).where(SiteManagerConnection.id == row.id).values(**changes))
        await session.refresh(row)
    return row


async def delete_connection(session: AsyncSession) -> SiteManagerConnection:
    row = await get_connection(session)
    await session.delete(row)
    await session.flush()
    return row
