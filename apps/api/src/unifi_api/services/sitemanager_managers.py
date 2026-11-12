"""API-owned account factory with database generations and request leases."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager
from unifi_core.sitemanager.managers.isp_metrics_manager import IspMetricsManager
from unifi_core.sitemanager.managers.sdwan_manager import SdwanManager

from unifi_api.services.sitemanager_connections import (
    SiteManagerConfigurationError,
    associated_data,
    get_connection,
)
from unifi_api.services.sitemanager_errors import SiteManagerAPIError, map_error


def _build_sitemanager_managers(connection):
    return {
        "inventory_manager": InventoryManager(connection),
        "isp_metrics_manager": IspMetricsManager(connection),
        "sdwan_manager": SdwanManager(connection),
    }


async def _close_connection(connection):
    try:
        await connection.close()
    except Exception as exc:
        error = map_error(exc, "close Site Manager connection")
    else:
        return
    raise error from None


async def _cleanup(awaitable):
    """Finish releasing resources even if the owning request is cancelled."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


@dataclass(eq=False, repr=False)
class SiteManagerBundle:
    connection_id: str
    revision: int
    connection: SiteManagerConnectionManager
    inventory_manager: InventoryManager
    isp_metrics_manager: IspMetricsManager
    sdwan_manager: SdwanManager
    leases: int = 0
    retired: bool = False
    drained: asyncio.Event = field(default_factory=asyncio.Event)


class SiteManagerFactory:
    """One live generation, with retired generations kept until their leases finish."""

    def __init__(self, sessionmaker, cipher):
        self._sessionmaker = sessionmaker
        self._cipher = cipher
        self._lock = asyncio.Lock()
        self._active = None
        self._bundles: set[SiteManagerBundle] = set()
        self._closed = False

    async def _row(self):
        async with self._sessionmaker() as session:
            return await get_connection(session)

    async def _build(self, row):
        key = None
        try:
            key = self._cipher.decrypt(row.api_key_blob, associated_data=associated_data(row.id)).decode()
            if not key.strip():
                raise ValueError("Empty stored key")
        except Exception:
            pass
        if key is None or not key.strip():
            raise SiteManagerConfigurationError("Cannot read the stored cloud key") from None
        connection = SiteManagerConnectionManager(api_key=key)
        try:
            await connection.initialize()
            managers = _build_sitemanager_managers(connection)
            return SiteManagerBundle(row.id, row.revision, connection, **managers)
        except BaseException:
            await _cleanup(_close_connection(connection))
            raise

    async def _close_bundle(self, bundle):
        try:
            await _close_connection(bundle.connection)
        finally:
            self._bundles.discard(bundle)
            bundle.drained.set()

    async def _retire(self, bundle):
        bundle.retired = True
        if bundle.leases == 0:
            await self._close_bundle(bundle)

    async def _release(self, bundle):
        async with self._lock:
            bundle.leases -= 1
            if bundle.retired and bundle.leases == 0:
                await self._close_bundle(bundle)

    @asynccontextmanager
    async def acquire(self):
        async with self._lock:
            if self._closed:
                raise SiteManagerConfigurationError("Cloud factory is closed")
            try:
                row = await self._row()
            except Exception:
                old, self._active = self._active, None
                if old is not None:
                    await _cleanup(self._retire(old))
                raise
            if self._active is not None and (self._active.connection_id, self._active.revision) != (
                row.id,
                row.revision,
            ):
                old, self._active = self._active, None
                await _cleanup(self._retire(old))
            if self._active is None:
                self._active = await self._build(row)
                self._bundles.add(self._active)
            bundle = self._active
            bundle.leases += 1
        try:
            yield bundle
        finally:
            await _cleanup(self._release(bundle))

    @asynccontextmanager
    async def isolated(self):
        """An explicit probe owns its connection and never alters cached requests."""
        async with self._lock:
            if self._closed:
                raise SiteManagerConfigurationError("Cloud factory is closed")
            bundle = await self._build(await self._row())
            bundle.leases = 1
            bundle.retired = True
            self._bundles.add(bundle)
        try:
            yield bundle
        finally:
            await _cleanup(self._release(bundle))

    async def invalidate(self):
        async with self._lock:
            old, self._active = self._active, None
            if old is not None:
                await _cleanup(self._retire(old))

    async def _shutdown(self):
        async with self._lock:
            self._closed = True
            self._active = None
            bundles = list(self._bundles)
            error = None
            for bundle in bundles:
                try:
                    await self._retire(bundle)
                except SiteManagerAPIError as exc:
                    error = exc
        for bundle in bundles:
            await bundle.drained.wait()
        if error is not None:
            raise error from None

    async def close(self):
        await _cleanup(self._shutdown())
