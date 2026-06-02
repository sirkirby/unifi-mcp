"""Per-controller manager factory.

Manual async-aware cache (NOT @lru_cache — async values + per-call session
arg make lru_cache the wrong tool). Per-controller asyncio.Lock around
construction prevents concurrent-cache-miss races.

Public surface:
- ManagerFactory(sessionmaker, cipher)
- get_connection_manager(session, controller_id, product) -> ConnectionManager
- get_domain_manager(session, controller_id, product, attr_name) -> domain manager
- invalidate_controller(controller_id)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from unifi_api.db.crypto import ColumnCipher
from unifi_api.db.models import Controller


class UnknownProduct(Exception):
    """Raised when a requested product is not supported by the controller."""


class UnknownManager(Exception):
    """Raised when a requested domain manager attribute is not registered."""


# Per-product mapping: runtime-singleton attribute name (as referenced by
# tool modules, e.g. ``client_manager``) -> a builder callable that
# constructs the domain manager from a connection_manager.
#
# Builders are lazy imports — they avoid importing unifi_core's
# product-specific modules at startup unless the product is actually used.


def _build_network_managers() -> dict[str, Callable[[Any], Any]]:
    from unifi_core.network.managers.acl_manager import AclManager
    from unifi_core.network.managers.client_group_manager import ClientGroupManager
    from unifi_core.network.managers.client_manager import ClientManager
    from unifi_core.network.managers.content_filter_manager import ContentFilterManager
    from unifi_core.network.managers.device_manager import DeviceManager
    from unifi_core.network.managers.dns_manager import DnsManager
    from unifi_core.network.managers.dpi_manager import DpiManager
    from unifi_core.network.managers.event_manager import EventManager
    from unifi_core.network.managers.firewall_manager import FirewallManager
    from unifi_core.network.managers.hotspot_manager import HotspotManager
    from unifi_core.network.managers.network_manager import NetworkManager
    from unifi_core.network.managers.oon_manager import OonManager
    from unifi_core.network.managers.qos_manager import QosManager
    from unifi_core.network.managers.routing_manager import RoutingManager
    from unifi_core.network.managers.stats_manager import StatsManager
    from unifi_core.network.managers.switch_manager import SwitchManager
    from unifi_core.network.managers.system_manager import SystemManager
    from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager
    from unifi_core.network.managers.usergroup_manager import UsergroupManager
    from unifi_core.network.managers.vpn_manager import VpnManager

    return {
        "acl_manager": lambda cm: AclManager(cm),
        "client_group_manager": lambda cm: ClientGroupManager(cm),
        "client_manager": lambda cm: ClientManager(cm),
        "content_filter_manager": lambda cm: ContentFilterManager(cm),
        "device_manager": lambda cm: DeviceManager(cm),
        "dns_manager": lambda cm: DnsManager(cm),
        # DpiManager takes (cm, auth). The connection manager carries a
        # UniFiAuth instance (see _construct_connection_manager); when no
        # API token is configured for the controller, the auth is unset
        # internally and DpiManager returns None with a clear log line.
        "dpi_manager": lambda cm: DpiManager(cm, getattr(cm, "unifi_auth", None)),
        "event_manager": lambda cm: EventManager(cm),
        "firewall_manager": lambda cm: FirewallManager(cm),
        "hotspot_manager": lambda cm: HotspotManager(cm),
        "network_manager": lambda cm: NetworkManager(cm),
        "oon_manager": lambda cm: OonManager(cm),
        "qos_manager": lambda cm: QosManager(cm),
        "routing_manager": lambda cm: RoutingManager(cm),
        # StatsManager takes (cm, client_manager) — circular for now, fail
        # at call time if needed.
        "stats_manager": lambda cm: StatsManager(cm, ClientManager(cm)),
        "switch_manager": lambda cm: SwitchManager(cm),
        "system_manager": lambda cm: SystemManager(cm),
        "traffic_route_manager": lambda cm: TrafficRouteManager(cm),
        "usergroup_manager": lambda cm: UsergroupManager(cm),
        "vpn_manager": lambda cm: VpnManager(cm),
    }


def _build_protect_managers() -> dict[str, Callable[[Any], Any]]:
    from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
    from unifi_core.protect.managers.alarm_manager import AlarmManager
    from unifi_core.protect.managers.camera_manager import CameraManager
    from unifi_core.protect.managers.chime_manager import ChimeManager
    from unifi_core.protect.managers.event_manager import EventManager
    from unifi_core.protect.managers.light_manager import LightManager
    from unifi_core.protect.managers.liveview_manager import LiveviewManager
    from unifi_core.protect.managers.recognition_manager import RecognitionManager
    from unifi_core.protect.managers.recording_manager import RecordingManager
    from unifi_core.protect.managers.sensor_manager import SensorManager
    from unifi_core.protect.managers.system_manager import SystemManager

    return {
        "alarm_manager": lambda cm: AlarmManager(cm),
        "alarm_facade": lambda cm: AlarmRulesFacade.from_connection(cm),
        "camera_manager": lambda cm: CameraManager(cm),
        "chime_manager": lambda cm: ChimeManager(cm),
        "event_manager": lambda cm: EventManager(cm),
        "light_manager": lambda cm: LightManager(cm),
        "liveview_manager": lambda cm: LiveviewManager(cm),
        "recognition_manager": lambda cm: RecognitionManager(cm),
        "recording_manager": lambda cm: RecordingManager(cm),
        "sensor_manager": lambda cm: SensorManager(cm),
        "system_manager": lambda cm: SystemManager(cm),
    }


def _build_access_managers() -> dict[str, Callable[[Any], Any]]:
    from unifi_core.access.managers.credential_manager import CredentialManager
    from unifi_core.access.managers.device_manager import DeviceManager
    from unifi_core.access.managers.door_manager import DoorManager
    from unifi_core.access.managers.event_manager import EventManager
    from unifi_core.access.managers.policy_manager import PolicyManager
    from unifi_core.access.managers.system_manager import SystemManager
    from unifi_core.access.managers.visitor_manager import VisitorManager

    return {
        "credential_manager": lambda cm: CredentialManager(cm),
        "device_manager": lambda cm: DeviceManager(cm),
        "door_manager": lambda cm: DoorManager(cm),
        "event_manager": lambda cm: EventManager(cm),
        "policy_manager": lambda cm: PolicyManager(cm),
        "system_manager": lambda cm: SystemManager(cm),
        "visitor_manager": lambda cm: VisitorManager(cm),
    }


_PRODUCT_BUILDERS: dict[str, Callable[[], dict[str, Callable[[Any], Any]]]] = {
    "network": _build_network_managers,
    "protect": _build_protect_managers,
    "access": _build_access_managers,
}


def _split_base_url(base_url: str) -> tuple[str, int]:
    """Parse a base URL into (host, port). Defaults to 443 when port absent."""
    parsed = urlparse(base_url)
    host = parsed.hostname or base_url
    port = parsed.port or 443
    return host, port


class ManagerFactory:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        cipher: ColumnCipher,
    ) -> None:
        self._sm = sessionmaker
        self._cipher = cipher
        self._connection_cache: dict[tuple[str, str], Any] = {}
        self._domain_cache: dict[tuple[str, str, str], Any] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._builder_cache: dict[str, dict[str, Callable[[Any], Any]]] = {}

    async def get_connection_manager(self, session: AsyncSession, controller_id: str, product: str) -> Any:
        key = (controller_id, product)
        cm = self._connection_cache.get(key)
        if cm is not None:
            return cm
        async with self._locks[controller_id]:
            cm = self._connection_cache.get(key)
            if cm is not None:
                return cm
            cm = await self._construct_connection_manager(session, controller_id, product)
            self._connection_cache[key] = cm
            return cm

    async def _construct_connection_manager(self, session: AsyncSession, controller_id: str, product: str) -> Any:
        controller = await session.get(Controller, controller_id)
        if controller is None:
            raise ValueError(f"controller {controller_id} not found")
        products = [p for p in controller.product_kinds.split(",") if p]
        if product not in products:
            raise UnknownProduct(f"controller {controller_id} does not support product '{product}'")
        creds = json.loads(self._cipher.decrypt(controller.credentials_blob))
        host, port = _split_base_url(controller.base_url)

        # ConnectionManager constructors all take (host, username, password,
        # port, verify_ssl, ...). They differ in optional kwargs:
        #   - network: site, cache_timeout, max_retries, retry_delay
        #   - protect: site, api_key
        #   - access:  api_key, api_port
        # Connections are NOT established at construction time — we must call
        # initialize() eagerly here so callers don't hang on the first
        # authenticated request. The MCP servers do this at startup; the
        # API service mirrors that contract. If initialize() raises (auth
        # failure, network error, etc.) the exception propagates so callers
        # see a clear error instead of a hang.
        if product == "network":
            from unifi_core.auth import UniFiAuth
            from unifi_core.network.managers.connection_manager import (
                ConnectionManager as NetCM,
            )

            cm: Any = NetCM(
                host=host,
                username=creds["username"],
                password=creds["password"],
                port=port,
                verify_ssl=controller.verify_tls,
            )
            # Stash a UniFiAuth carrying the controller's API token (if any)
            # so managers that hit the official integration API (DPI today,
            # potentially others later) can authenticate. None when the
            # operator hasn't provided a token; consuming managers handle
            # that case with a clear error rather than crashing.
            cm.unifi_auth = UniFiAuth(api_key=creds.get("api_token") or None)
            await cm.initialize()
            return cm
        if product == "protect":
            from unifi_core.protect.managers.connection_manager import (
                ProtectConnectionManager as ProtectCM,
            )

            cm = ProtectCM(
                host=host,
                username=creds["username"],
                password=creds["password"],
                port=port,
                verify_ssl=controller.verify_tls,
                api_key=creds.get("api_token"),
            )
            await cm.initialize()
            return cm
        if product == "access":
            from unifi_core.access.managers.connection_manager import (
                AccessConnectionManager as AccessCM,
            )

            cm = AccessCM(
                host=host,
                username=creds["username"],
                password=creds["password"],
                port=port,
                verify_ssl=controller.verify_tls,
                api_key=creds.get("api_token"),
            )
            await cm.initialize()
            return cm
        raise UnknownProduct(f"unknown product '{product}'")

    def _builders_for(self, product: str) -> dict[str, Callable[[Any], Any]]:
        """Lazy-load (and cache) the per-product domain manager builder map."""
        cached = self._builder_cache.get(product)
        if cached is not None:
            return cached
        builder_factory = _PRODUCT_BUILDERS.get(product)
        if builder_factory is None:
            raise UnknownProduct(f"unknown product '{product}'")
        builders = builder_factory()
        self._builder_cache[product] = builders
        return builders

    async def get_domain_manager(
        self,
        session: AsyncSession,
        controller_id: str,
        product: str,
        attr_name: str,
    ) -> Any:
        """Resolve a per-controller domain manager by its runtime attribute name.

        ``attr_name`` matches the singleton attribute used by the MCP runtime
        modules (e.g. ``client_manager`` from ``unifi_network_mcp.runtime``).

        Cached on (controller_id, product, attr_name). Does NOT take the
        per-controller lock here — get_connection_manager already serializes
        the slow path (initialize()), and the rest of this function is a
        synchronous builder call where a brief race on first-use produces
        last-writer-wins on the cache, which is harmless because builders
        are pure and share the cached connection manager.

        Acquiring the lock here would deadlock — it's non-reentrant and
        get_connection_manager acquires the same lock.
        """
        key = (controller_id, product, attr_name)
        cached = self._domain_cache.get(key)
        if cached is not None:
            return cached
        builders = self._builders_for(product)
        builder = builders.get(attr_name)
        if builder is None:
            raise UnknownManager(f"product '{product}' has no domain manager named '{attr_name}'")
        cm = await self.get_connection_manager(session, controller_id, product)
        instance = builder(cm)
        self._domain_cache[key] = instance
        return instance

    async def probe_controller(self, controller_id: str) -> dict:
        """Live connectivity probe across all products the controller advertises.

        Invalidates any cached connection for the controller, then reconstructs
        each product's ConnectionManager (which calls initialize() — the network
        round-trip). Per-product latency + success/failure.

        Returns:
            {
              "ok": <bool — all products succeeded>,
              "products": {<product>: {"ok": bool, "latency_ms": int, "error": <str|None>}, ...},
              "latency_ms": <int — sum of per-product latencies>,
              "error_kind": <"not_found" | None>,
              "last_probed_at": <iso8601 utc str>,
            }

        If the controller does not exist, returns:
            {"ok": False, "error_kind": "not_found", "products": {},
             "latency_ms": 0, "last_probed_at": iso8601}

        This method does NOT cache the constructed connection. After the probe,
        the controller's connection cache is empty. The next normal request
        will reconstruct cleanly. This is intentional (probe = fresh handshake).
        """
        async with self._sm() as session:
            controller = await session.get(Controller, controller_id)
            if controller is None:
                return {
                    "ok": False,
                    "error_kind": "not_found",
                    "products": {},
                    "latency_ms": 0,
                    "last_probed_at": datetime.now(timezone.utc).isoformat(),
                }
            products = [p for p in controller.product_kinds.split(",") if p]

        # Drop cached connections so we exercise the slow path.
        await self.invalidate_controller(controller_id)

        per_product: dict[str, dict] = {}
        total_latency = 0
        all_ok = True
        for product in products:
            start = time.perf_counter()
            try:
                async with self._sm() as session:
                    await self._construct_connection_manager(session, controller_id, product)
                latency = int((time.perf_counter() - start) * 1000)
                per_product[product] = {"ok": True, "latency_ms": latency, "error": None}
                total_latency += latency
            except Exception as exc:
                latency = int((time.perf_counter() - start) * 1000)
                per_product[product] = {"ok": False, "latency_ms": latency, "error": str(exc)}
                total_latency += latency
                all_ok = False

        return {
            "ok": all_ok,
            "products": per_product,
            "latency_ms": total_latency,
            "error_kind": None,
            "last_probed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def invalidate_controller(self, controller_id: str) -> None:
        """Drop all cached managers for a controller and dispose their sessions."""
        keys_conn = [k for k in self._connection_cache if k[0] == controller_id]
        for k in keys_conn:
            cm = self._connection_cache.pop(k)
            close = getattr(cm, "close", None) or getattr(cm, "aclose", None)
            if close is not None:
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
        keys_domain = [k for k in self._domain_cache if k[0] == controller_id]
        for k in keys_domain:
            self._domain_cache.pop(k, None)
