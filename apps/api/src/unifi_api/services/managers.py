"""Per-controller manager factory.

Manual async-aware cache (NOT @lru_cache — async values + per-call session
arg make lru_cache the wrong tool). Per-controller asyncio.Lock around
construction prevents concurrent-cache-miss races.

Public surface:
- ManagerFactory(sessionmaker, cipher)
- get_connection_manager(session, controller_id, product, site=...) -> ConnectionManager
- get_domain_manager(session, controller_id, product, attr_name, site=...) -> domain manager
- invalidate_controller(controller_id)

Network connection and domain-manager caches include the site. A cached
Network manager therefore never changes site after construction, so
concurrent requests for different sites cannot race through mutable shared
ConnectionManager state. Protect and Access have no Network site namespace;
their cache identity remains controller + product.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from unifi_api.db.crypto import ColumnCipher
from unifi_api.db.models import Controller

logger = logging.getLogger(__name__)


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
    from unifi_core.network.managers.dynamic_dns_manager import DynamicDnsManager
    from unifi_core.network.managers.event_manager import EventManager
    from unifi_core.network.managers.firewall_manager import FirewallManager
    from unifi_core.network.managers.gateway_settings_manager import GatewaySettingsManager
    from unifi_core.network.managers.hotspot_manager import HotspotManager
    from unifi_core.network.managers.network_manager import NetworkManager
    from unifi_core.network.managers.oon_manager import OonManager
    from unifi_core.network.managers.qos_manager import QosManager
    from unifi_core.network.managers.routing_manager import RoutingManager
    from unifi_core.network.managers.stats_manager import StatsManager
    from unifi_core.network.managers.switch_manager import SwitchManager
    from unifi_core.network.managers.system_manager import SystemManager
    from unifi_core.network.managers.traffic_flow_manager import TrafficFlowManager
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
        "dynamic_dns_manager": lambda cm: DynamicDnsManager(cm),
        "event_manager": lambda cm: EventManager(cm),
        "firewall_manager": lambda cm: FirewallManager(cm),
        "gateway_settings_manager": lambda cm: GatewaySettingsManager(cm),
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
        "traffic_flow_manager": lambda cm: TrafficFlowManager(cm),
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
        self._connection_cache: dict[tuple[str, str, str | None], Any] = {}
        self._domain_cache: dict[tuple[str, str, str, str | None], Any] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._builder_cache: dict[str, dict[str, Callable[[Any], Any]]] = {}

    @staticmethod
    def _site_scope(product: str, site: str | None) -> str | None:
        """Return the cache scope for a product.

        Only Network has a controller-side site namespace. Treat an omitted
        Network site as ``default`` so existing non-site-specific control
        paths keep their historical behavior without sharing an instance
        with an explicitly selected site.
        """
        if product == "network":
            return site or "default"
        return None

    @staticmethod
    async def _close_connection_manager(cm: Any) -> None:
        close = getattr(cm, "close", None) or getattr(cm, "aclose", None) or getattr(cm, "cleanup", None)
        if close is None:
            return
        result = close()
        if asyncio.iscoroutine(result):
            await result

    @classmethod
    async def _require_initialized(cls, cm: Any, product: str) -> Any:
        try:
            initialized = await cm.initialize()
        except BaseException:
            try:
                await asyncio.shield(cls._close_connection_manager(cm))
            except BaseException as cleanup_error:
                logger.warning(
                    "Failed to close %s connection after initialization error: %s",
                    product,
                    cleanup_error,
                )
            raise
        if initialized is True:
            return cm
        detail = getattr(cm, "last_connection_error", None)
        try:
            await cls._close_connection_manager(cm)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to close %s connection after unsuccessful initialization: %s",
                product,
                cleanup_error,
            )
        suffix = f": {detail}" if detail else ""
        raise ConnectionError(f"Failed to initialize {product} controller connection{suffix}")

    async def get_connection_manager(
        self,
        session: AsyncSession,
        controller_id: str,
        product: str,
        *,
        site: str | None = None,
    ) -> Any:
        site_scope = self._site_scope(product, site)
        key = (controller_id, product, site_scope)
        cm = self._connection_cache.get(key)
        if cm is not None:
            return cm
        async with self._locks[controller_id]:
            cm = self._connection_cache.get(key)
            if cm is not None:
                return cm
            cm = await self._construct_connection_manager(
                session,
                controller_id,
                product,
                site=site_scope,
            )
            self._connection_cache[key] = cm
            return cm

    async def _construct_connection_manager(
        self,
        session: AsyncSession,
        controller_id: str,
        product: str,
        *,
        site: str | None = None,
    ) -> Any:
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
                site=site or "default",
                verify_ssl=controller.verify_tls,
            )
            # Stash a UniFiAuth carrying the controller's API token (if any)
            # so managers that hit the official integration API (DPI today,
            # potentially others later) can authenticate. None when the
            # operator hasn't provided a token; consuming managers handle
            # that case with a clear error rather than crashing.
            cm.unifi_auth = UniFiAuth(api_key=creds.get("api_token") or None)
            return await self._require_initialized(cm, product)
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
            return await self._require_initialized(cm, product)
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
            return await self._require_initialized(cm, product)
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
        *,
        site: str | None = None,
    ) -> Any:
        """Resolve a per-controller domain manager by its runtime attribute name.

        ``attr_name`` matches the singleton attribute used by the MCP runtime
        modules (e.g. ``client_manager`` from ``unifi_network_mcp.runtime``).

        Network managers are cached on
        (controller_id, product, attr_name, site). Other products use a null
        site scope. Does NOT take the per-controller lock here —
        get_connection_manager already serializes the slow path
        (initialize()), and the rest of this function is a synchronous builder
        call where a brief race on first-use produces last-writer-wins on the
        cache, which is harmless because builders are pure and share the
        cached connection manager for the same site.

        Acquiring the lock here would deadlock — it's non-reentrant and
        get_connection_manager acquires the same lock.
        """
        site_scope = self._site_scope(product, site)
        key = (controller_id, product, attr_name, site_scope)
        cached = self._domain_cache.get(key)
        if cached is not None:
            return cached
        builders = self._builders_for(product)
        builder = builders.get(attr_name)
        if builder is None:
            raise UnknownManager(f"product '{product}' has no domain manager named '{attr_name}'")
        cm = await self.get_connection_manager(
            session,
            controller_id,
            product,
            site=site_scope,
        )
        instance = builder(cm)
        self._domain_cache[key] = instance
        return instance

    async def probe_controller(self, controller_id: str) -> dict:
        """Live connectivity probe across all products the controller advertises.

        Constructs an isolated ConnectionManager for each product (including
        initialize() and the network round-trip), then closes it without touching
        cached production request sessions. Per-product latency + success/failure.

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

        This method does NOT cache the constructed connection and leaves
        healthy cached sessions untouched — a health probe must not interrupt
        in-flight production requests. The one exception: cached connections
        whose auth circuit latched are dropped after their product probes ok,
        so production traffic recovers as soon as credentials work again.
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

        # Probes construct isolated managers and must not disrupt cached
        # production request sessions.
        per_product: dict[str, dict] = {}
        total_latency = 0
        all_ok = True
        for product in products:
            start = time.perf_counter()
            cm = None
            try:
                async with self._sm() as session:
                    cm = await self._construct_connection_manager(session, controller_id, product)
                latency = int((time.perf_counter() - start) * 1000)
                per_product[product] = {"ok": True, "latency_ms": latency, "error": None}
                total_latency += latency
            except Exception as exc:
                latency = int((time.perf_counter() - start) * 1000)
                per_product[product] = {"ok": False, "latency_ms": latency, "error": str(exc)}
                total_latency += latency
                all_ok = False
            finally:
                if cm is not None:
                    try:
                        await self._close_connection_manager(cm)
                    except Exception as exc:
                        logger.warning("Failed to close %s probe connection: %s", product, exc)
                        previous = per_product.get(product, {})
                        per_product[product] = {
                            "ok": False,
                            "latency_ms": previous.get("latency_ms", 0),
                            "error": f"Probe cleanup failed: {exc}",
                        }
                        all_ok = False

        await self._heal_blocked_connections(controller_id, per_product)

        return {
            "ok": all_ok,
            "products": per_product,
            "latency_ms": total_latency,
            "error_kind": None,
            "last_probed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _heal_blocked_connections(self, controller_id: str, per_product: dict[str, dict]) -> None:
        """Drop cached connections whose auth circuit latched once a probe proves auth works.

        A successful isolated probe means credentials and reachability are good
        again; keeping a cached connection that latched its reconnect block
        would leave production requests failing until the block's cool-down
        expires. Healthy cached connections are left untouched.
        """
        async with self._locks[controller_id]:
            healable = [
                key
                for key, cached in self._connection_cache.items()
                if key[0] == controller_id
                and getattr(cached, "reconnect_blocked", False)
                and per_product.get(key[1], {}).get("ok")
            ]
            if not healable:
                return
            # Domain managers may be bound to the blocked connections; sweep
            # them synchronously with the pops (same invariant as
            # invalidate_controller). Survivors rebuild from cached healthy
            # connections on next use.
            for k in [k for k in self._domain_cache if k[0] == controller_id]:
                self._domain_cache.pop(k, None)
            removed = [self._connection_cache.pop(k) for k in healable]
            logger.info(
                "Probe succeeded; dropping %d auth-blocked cached connection(s) for controller %s",
                len(removed),
                controller_id,
            )
            for cm in removed:
                try:
                    await self._close_connection_manager(cm)
                except Exception as exc:
                    logger.warning("Failed to close auth-blocked connection for controller %s: %s", controller_id, exc)

    async def invalidate_controller(self, controller_id: str) -> None:
        """Drop all cached managers for a controller and dispose their sessions."""
        async with self._locks[controller_id]:
            # Sweep both caches synchronously (no awaits between the sweeps) so
            # the lock-free read paths can never observe a half-invalidated
            # state: a domain-cache miss followed by a connection-cache hit on
            # an entry still awaiting close would rebuild a domain manager
            # around a disposed session and its pre-rotation credentials.
            for k in [k for k in self._domain_cache if k[0] == controller_id]:
                self._domain_cache.pop(k, None)
            removed = [
                self._connection_cache.pop(k) for k in [k for k in self._connection_cache if k[0] == controller_id]
            ]
            for cm in removed:
                try:
                    await self._close_connection_manager(cm)
                except Exception as exc:
                    logger.warning("Failed to close invalidated controller connection %s: %s", controller_id, exc)
