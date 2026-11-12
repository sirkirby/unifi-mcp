"""Cloud storage is singleton, encrypted, revisioned, and separate from consoles."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.engine import create_engine
from unifi_api.db.models import AuditLog, Base, Controller, SiteManagerConnection
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.audit import write_audit
from unifi_api.services.sitemanager_connections import (
    SiteManagerConnectionConflict,
    SiteManagerConnectionNotFound,
    associated_data,
    create_connection,
    delete_connection,
    get_connection,
    metadata,
    update_connection,
)
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

from tests.sitemanager_secrets import KEY


@pytest_asyncio.fixture
async def store(tmp_path):
    engine = create_engine(tmp_path / "cloud.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield get_sessionmaker(engine), ColumnCipher(derive_key("synthetic-db-passphrase"))
    await engine.dispose()


async def seed(store):
    sm, cipher = store
    async with sm() as session:
        row = await create_connection(
            session, cipher, SiteManagerConnectionCreate(name="Account", site_manager_api_key=KEY)
        )
        await session.commit()
        return row


@pytest.mark.asyncio
async def test_storage_crud_and_isolation(store, cloud_secrecy_guard):
    sm, cipher = store
    row = await seed(store)
    assert KEY.encode() not in row.api_key_blob
    assert cipher.decrypt(row.api_key_blob, associated_data=associated_data(row.id)).decode() == KEY
    for aad in (None, associated_data("different-local-id")):
        with pytest.raises(InvalidTag):
            cipher.decrypt(row.api_key_blob, associated_data=aad)
    assert set(metadata(row)) == {"id", "name", "key_configured", "revision", "created_at", "updated_at"}
    cloud_secrecy_guard(str(metadata(row)))
    async with sm() as session:
        assert (await session.scalars(select(Controller))).all() == []
        before = metadata(await get_connection(session))
        unchanged = await update_connection(session, cipher, SiteManagerConnectionPatch())
        assert metadata(unchanged) == before
        renamed = await update_connection(session, cipher, SiteManagerConnectionPatch(name="Renamed"))
        assert renamed.revision == 2
        assert renamed.api_key_blob == row.api_key_blob
        rotated = await update_connection(
            session, cipher, SiteManagerConnectionPatch(site_manager_api_key="rotated-synthetic")
        )
        assert rotated.revision == 3
        assert rotated.name == "Renamed"
        await session.commit()
    async with sm() as session:
        await delete_connection(session)
        await session.commit()
    async with sm() as session:
        with pytest.raises(SiteManagerConnectionNotFound):
            await get_connection(session)
    replacement = await seed(store)
    assert replacement.id != row.id


@pytest.mark.asyncio
async def test_singleton_conflict_and_database_checks(store, cloud_secrecy_guard):
    sm, cipher = store
    await seed(store)
    async with sm() as session:
        with pytest.raises(SiteManagerConnectionConflict):
            await create_connection(
                session, cipher, SiteManagerConnectionCreate(name="Other", site_manager_api_key=KEY)
            )
        await session.rollback()
        assert (await get_connection(session)).name == "Account"
    # Even bypassing the service cannot insert a second row or another slot.
    for slot, revision in [(1, 1), (2, 1), (1, 0)]:
        async with sm() as session:
            now = datetime.now(timezone.utc)
            session.add(
                SiteManagerConnection(
                    id="synthetic-local-id",
                    singleton_slot=slot,
                    name="Other",
                    api_key_blob=b"x",
                    revision=revision,
                    created_at=now,
                    updated_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()


@pytest.mark.asyncio
async def test_audit_identity_survives_deletion_and_rejects_mixed_target(store, cloud_secrecy_guard):
    sm, _ = store
    row = await seed(store)
    async with sm() as session:
        with pytest.raises(ValueError):
            await write_audit(
                session,
                key_id_prefix="(cli)",
                controller="console",
                sitemanager_connection=row.id,
                target="sitemanager.create",
                outcome="success",
            )
        await write_audit(
            session,
            key_id_prefix="(cli)",
            controller=None,
            sitemanager_connection=row.id,
            target="sitemanager.create",
            outcome="success",
        )
        await delete_connection(session)
        await session.commit()
    async with sm() as session:
        audits = (await session.scalars(select(AuditLog))).all()
        assert len(audits) == 1
        assert audits[0].sitemanager_connection == row.id
        assert audits[0].controller is None
        assert audits[0].detail is None


@pytest.mark.parametrize("products", [["sitemanager"], ["unknown"], ["network", "sitemanager"]])
def test_shared_console_validator_rejects_cloud(products, cloud_secrecy_guard):
    from fastapi import HTTPException
    from unifi_api.routes.admin.controllers import _parse_product_kinds
    from unifi_api.services.controllers import InvalidControllerCredentials, validate_controller_credentials

    with pytest.raises(InvalidControllerCredentials):
        validate_controller_credentials(products, "u", "p", None)
    with pytest.raises(HTTPException) as error:
        _parse_product_kinds(products)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_singleton_constraint_rejects_concurrent_create(store, cloud_secrecy_guard):
    import asyncio

    sm, cipher = store

    async def create():
        async with sm() as session:
            try:
                row = await create_connection(
                    session, cipher, SiteManagerConnectionCreate(name="Account", site_manager_api_key=KEY)
                )
                await session.commit()
                return row.id
            except SiteManagerConnectionConflict:
                await session.rollback()
                return None

    results = await asyncio.gather(create(), create())
    assert len([result for result in results if result]) == 1
    async with sm() as session:
        rows = (await session.scalars(select(SiteManagerConnection))).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_revisions_use_database_arithmetic_across_sessions(store, cloud_secrecy_guard):
    import asyncio

    sm, cipher = store
    await seed(store)

    async def rotate():
        async with sm() as session:
            await update_connection(
                session, cipher, SiteManagerConnectionPatch(site_manager_api_key="rotated-synthetic")
            )
            await session.commit()

    await asyncio.gather(*(rotate() for _ in range(5)))
    async with sm() as session:
        assert (await get_connection(session)).revision == 6


@pytest.mark.asyncio
async def test_console_and_cloud_ciphertext_cannot_cross_credential_paths(store, cloud_secrecy_guard):
    from unifi_api.services.controllers import CreateControllerPayload, create_controller, update_controller
    from unifi_api.services.sitemanager_connections import SiteManagerConfigurationError
    from unifi_api.services.sitemanager_managers import SiteManagerFactory

    sm, cipher = store
    cloud = await seed(store)
    async with sm() as session:
        console = await create_controller(
            session,
            cipher,
            CreateControllerPayload(
                name="Console",
                base_url="https://192.0.2.1",
                product_kinds=["network"],
                username="synthetic-console-user",
                password="synthetic-console-password",
                api_token="synthetic-console-token",
                verify_tls=True,
                is_default=True,
            ),
        )
        await session.commit()
    with pytest.raises(InvalidTag):
        cipher.decrypt(console.credentials_blob, associated_data=associated_data(cloud.id))
    with pytest.raises(InvalidTag):
        cipher.decrypt(cloud.api_key_blob)
    # Exercise each actual consumer with ciphertext transplanted from the other path.
    async with sm() as session:
        stored = await session.get(SiteManagerConnection, cloud.id)
        stored.api_key_blob = console.credentials_blob
        stored_console = await session.get(Controller, console.id)
        stored_console.credentials_blob = cloud.api_key_blob
        await session.commit()
    factory = SiteManagerFactory(sm, cipher)
    try:
        with pytest.raises(SiteManagerConfigurationError):
            async with factory.acquire():
                pytest.fail("Cloud factory accepted console ciphertext")
        async with sm() as session:
            with pytest.raises(InvalidTag):
                await update_controller(session, cipher, console.id, api_token="synthetic-replacement")
    finally:
        await factory.close()
