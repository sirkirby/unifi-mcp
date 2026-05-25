import logging
from types import SimpleNamespace
from typing import Any, List, Optional

from aiounifi.models.api import ApiRequest
from aiounifi.models.client import Client

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_CLIENTS = "clients"


class ClientManager:
    """Manages client-related operations on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Client Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_clients(self) -> List[Client]:
        """Get list of currently online clients for the current site."""
        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_CLIENTS}_online_{self._connection.site}"
        cached_data: Optional[List[Client]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            await self._connection.controller.clients.update()
            clients: List[Client] = list(self._connection.controller.clients.values())
            # Fallback rationale:
            # - Some controller models/versions may not populate the collection
            #   via controller.clients.update().
            # - UniFi API semantics: active/online clients are served from
            #   /stat/sta, while historical/all clients are under /rest/user.
            #   Therefore for "online" we fallback to GET /stat/sta.
            if not clients:
                try:
                    raw_clients = await self._connection.request(ApiRequest(method="get", path="/stat/sta"))
                    if isinstance(raw_clients, list) and raw_clients:
                        # Cache raw dicts; tool layer handles dict or Client
                        self._connection._update_cache(cache_key, raw_clients)
                        return raw_clients  # type: ignore[return-value]
                except Exception as fallback_e:
                    logger.debug("Raw clients fallback failed: %s", fallback_e)
            self._connection._update_cache(cache_key, clients)
            return clients
        except Exception as e:
            logger.error("Error getting online clients: %s", e)
            raise

    async def get_all_clients(self) -> List[Client]:
        """Get list of all clients (including offline/historical) for the current site."""
        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_CLIENTS}_all_{self._connection.site}"
        cached_data: Optional[List[Client]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            await self._connection.controller.clients_all.update()
            all_clients: List[Client] = list(self._connection.controller.clients_all.values())
            # Fallback rationale:
            # - When the clients_all collection is empty, query the canonical
            #   UniFi endpoint for all/historical client records.
            # - UniFi API semantics: GET /rest/user returns all known clients
            #   (legacy naming "user" == client record), not only currently
            #   connected. This complements GET /stat/sta used for online-only.
            if not all_clients:
                try:
                    raw_all = await self._connection.request(ApiRequest(method="get", path="/rest/user"))
                    if isinstance(raw_all, list) and raw_all:
                        self._connection._update_cache(cache_key, raw_all)
                        return raw_all  # type: ignore[return-value]
                except Exception as fallback_e:
                    logger.debug("Raw all-clients fallback failed: %s", fallback_e)
            self._connection._update_cache(cache_key, all_clients)
            return all_clients
        except Exception as e:
            logger.error("Error getting all clients: %s", e)
            raise

    @staticmethod
    def _mac_of(c: Any) -> Optional[str]:
        if isinstance(c, dict):
            return c.get("mac")
        raw = getattr(c, "raw", None)
        if isinstance(raw, dict):
            return raw.get("mac")
        return getattr(c, "mac", None)

    @staticmethod
    def _raw_of(c: Any) -> dict:
        if c is None:
            return {}
        if isinstance(c, dict):
            return c
        raw = getattr(c, "raw", None)
        return raw if isinstance(raw, dict) else {}

    async def get_client_details(self, client_mac: str) -> Any:
        """Get detailed information for a specific client by MAC address.

        Returns a merged view combining /stat/sta (live data: fresh
        timestamps, uptime, signal, traffic) with /rest/user (stable
        user-table fields: _id, noted, fixed_ip, alias). For currently-
        connected clients, the result has the best of both endpoints; for
        offline clients (not in /stat/sta) it falls back to just /rest/user.

        Each endpoint is queried independently so a transient failure on
        one does not block the lookup.

        Returns:
            An object with stable ``.mac`` and ``.raw`` attributes so
            callers (rename_client, set_client_ip_settings, etc.) can
            uniformly access the raw payload regardless of which endpoint
            it came from.

        Raises:
            UniFiNotFoundError: If at least one endpoint succeeded and
                neither contained the requested MAC.
            Original underlying exception: If *both* endpoints failed
                (e.g., controller offline) — re-raised so callers see an
                accurate failure cause instead of a misleading not-found.
        """
        active_record: Optional[Any] = None
        active_error: Optional[Exception] = None
        try:
            active = await self.get_clients()
            for c in active:
                if self._mac_of(c) == client_mac:
                    active_record = c
                    break
        except Exception as e:
            active_error = e
            logger.debug("/stat/sta fetch failed during get_client_details: %s", e)

        user_record: Optional[Any] = None
        user_error: Optional[Exception] = None
        try:
            all_clients = await self.get_all_clients()
            for c in all_clients:
                if self._mac_of(c) == client_mac:
                    user_record = c
                    break
        except Exception as e:
            user_error = e
            logger.debug("/rest/user fetch failed during get_client_details: %s", e)

        if active_record is None and user_record is None:
            if active_error is not None and user_error is not None:
                # Both endpoints failed — surface the underlying connectivity/
                # outage error rather than misreporting it as a not-found.
                raise active_error
            raise UniFiNotFoundError("client", client_mac)

        active_raw = self._raw_of(active_record)
        user_raw = self._raw_of(user_record)

        if active_raw and user_raw:
            # /stat/sta wins for overlapping keys (live data trumps stale snapshot);
            # /rest/user supplies stable user-table fields (_id, noted, fixed_ip,
            # local_dns_record, usergroup_id) that /stat/sta sometimes omits.
            merged_raw = {**user_raw, **active_raw}
            return SimpleNamespace(mac=client_mac, raw=merged_raw)

        # Single-source: normalize to the same `.mac`/`.raw` contract so all
        # callers can rely on attribute access without runtime type checks.
        single = active_record if active_record is not None else user_record
        single_raw = active_raw or user_raw
        if isinstance(single, dict):
            return SimpleNamespace(mac=single.get("mac"), raw=single)
        if not hasattr(single, "raw") or not isinstance(getattr(single, "raw", None), dict):
            return SimpleNamespace(mac=self._mac_of(single), raw=single_raw)
        return single

    async def block_client(self, client_mac: str) -> bool:
        """Block a client by MAC address.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        await self.get_client_details(client_mac)  # existence check; raises on miss
        try:
            # Construct ApiRequest
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "block-sta"},
            )
            # Call the updated request method
            await self._connection.request(api_request)
            logger.info("Block command sent for client %s", client_mac)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")  # Invalidate all client caches
            return True
        except Exception as e:
            logger.error("Error blocking client %s: %s", client_mac, e)
            raise

    async def unblock_client(self, client_mac: str) -> bool:
        """Unblock a client by MAC address.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        await self.get_client_details(client_mac)  # existence check; raises on miss
        try:
            # Construct ApiRequest
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "unblock-sta"},
            )
            # Call the updated request method
            await self._connection.request(api_request)
            logger.info("Unblock command sent for client %s", client_mac)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error unblocking client %s: %s", client_mac, e)
            raise

    async def rename_client(self, client_mac: str, name: str) -> bool:
        """Rename a client device.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        try:
            client = await self.get_client_details(client_mac)  # raises on miss
            if "_id" not in client.raw:
                logger.error("Cannot rename client %s: missing _id in raw payload.", client_mac)
                return False
            client_id = client.raw["_id"]

            # Use REST endpoint (consistent with set_client_ip_settings).
            # Fall back to legacy /upd/user/ for older standalone controllers.
            try:
                api_request = ApiRequest(method="put", path=f"/rest/user/{client_id}", data={"name": name})
                await self._connection.request(api_request)
            except Exception as e:
                logger.debug(
                    "REST endpoint failed for rename, falling back to legacy /upd/user/ for %s: %s",
                    client_mac,
                    e,
                    exc_info=True,
                )
                api_request = ApiRequest(method="put", path=f"/upd/user/{client_id}", data={"name": name})
                await self._connection.request(api_request)
            logger.info("Rename command sent for client %s to '%s'", client_mac, name)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error renaming client %s to '%s': %s", client_mac, name, e)
            raise

    async def force_reconnect_client(self, client_mac: str) -> bool:
        """Force a client to reconnect (kick).

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        await self.get_client_details(client_mac)  # existence check; raises on miss
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "kick-sta"},
            )
            await self._connection.request(api_request)
            logger.info("Force reconnect (kick) command sent for client %s", client_mac)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error forcing reconnect for client %s: %s", client_mac, e)
            raise

    async def forget_client(self, client_mac: str) -> bool:
        """Forget/remove a client from the controller's known client history.

        Idempotent: forgetting an unknown MAC returns success (the controller
        also accepts unknown MACs without erroring), preserving the
        delete-style semantics from spec §6.3.
        """
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"macs": [client_mac], "cmd": "forget-sta"},
            )
            await self._connection.request(api_request)
            logger.info("Forget command sent for client %s", client_mac)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error forgetting client %s: %s", client_mac, e)
            raise

    async def get_blocked_clients(self) -> List[Client]:
        """Get a list of currently blocked clients."""
        all_clients = await self.get_all_clients()
        blocked: List[Client] = [client for client in all_clients if client.blocked]
        return blocked

    async def authorize_guest(
        self,
        client_mac: str,
        minutes: int,
        up_kbps: Optional[int] = None,
        down_kbps: Optional[int] = None,
        bytes_quota: Optional[int] = None,
    ) -> bool:
        """Authorize a guest client.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        await self.get_client_details(client_mac)  # existence check; raises on miss
        try:
            payload = {"mac": client_mac, "cmd": "authorize-guest", "minutes": minutes}
            if up_kbps is not None:
                payload["up"] = up_kbps
            if down_kbps is not None:
                payload["down"] = down_kbps
            if bytes_quota is not None:
                payload["bytes"] = bytes_quota

            # Construct ApiRequest
            api_request = ApiRequest(method="post", path="/cmd/stamgr", data=payload)
            # Call the updated request method
            await self._connection.request(api_request)
            logger.info("Authorize command sent for guest %s for %s minutes", client_mac, minutes)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error authorizing guest %s: %s", client_mac, e)
            raise

    async def unauthorize_guest(self, client_mac: str) -> bool:
        """Unauthorize (de-authorize) a guest client.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        await self.get_client_details(client_mac)  # existence check; raises on miss
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "unauthorize-guest"},
            )
            await self._connection.request(api_request)
            logger.info("Unauthorize command sent for guest %s", client_mac)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error unauthorizing guest %s: %s", client_mac, e)
            raise

    async def get_client_by_ip(self, ip_address: str) -> Optional[Client]:
        """Get client information by IP address.

        Searches online clients first, then falls back to all clients
        (including offline/historical) to avoid stale IP matches.

        Args:
            ip_address: The IP address to search for.

        Returns:
            Client object if found, None otherwise.
        """
        import re

        if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_address):
            return None

        # Search online clients first to avoid stale IP assignments
        online_clients = await self.get_clients()
        match: Optional[Client] = next((c for c in online_clients if c.ip == ip_address), None)
        if match:
            return match

        # Fallback to all clients (including offline/historical)
        all_clients = await self.get_all_clients()
        return next((c for c in all_clients if c.ip == ip_address), None)

    async def set_client_ip_settings(
        self,
        client_mac: str,
        use_fixedip: Optional[bool] = None,
        fixed_ip: Optional[str] = None,
        local_dns_record_enabled: Optional[bool] = None,
        local_dns_record: Optional[str] = None,
    ) -> bool:
        """Set fixed IP and/or local DNS record for a client.

        Uses the UniFi REST API endpoint PUT /rest/user/{client_id}.
        Local DNS records require UniFi Network 7.2+.

        Args:
            client_mac: MAC address of the client to update.
            use_fixedip: Enable (True) or disable (False) fixed IP.
            fixed_ip: The fixed IP address to assign (required if use_fixedip=True).
            local_dns_record_enabled: Enable (True) or disable (False) local DNS.
            local_dns_record: The DNS hostname to assign (e.g., "mydevice.local").

        Returns:
            True if the update was successful, False otherwise.
        """
        try:
            # Get client to find their internal _id; raises UniFiNotFoundError on miss.
            client = await self.get_client_details(client_mac)

            client_raw = client.raw if hasattr(client, "raw") else client
            if "_id" not in client_raw:
                logger.error("Cannot set IP settings for %s: Missing _id", client_mac)
                return False

            client_id = client_raw["_id"]

            # If client is not "noted" (known), mark it first to enable IP config
            if not client_raw.get("noted"):
                logger.info("Client %s not noted, marking as known first", client_mac)
                note_payload = {"noted": True}
                if not client_raw.get("name") and client_raw.get("hostname"):
                    note_payload["name"] = client_raw["hostname"]
                try:
                    note_request = ApiRequest(
                        method="put",
                        path=f"/rest/user/{client_id}",
                        data=note_payload,
                    )
                    await self._connection.request(note_request)
                except Exception as note_err:
                    logger.warning("Could not mark client as noted: %s", note_err)

            # Build payload with only explicitly provided fields
            payload: dict = {}

            if use_fixedip is not None:
                payload["use_fixedip"] = use_fixedip
                if use_fixedip and fixed_ip:
                    payload["fixed_ip"] = fixed_ip
                elif not use_fixedip:
                    payload["fixed_ip"] = ""
            elif fixed_ip is not None:
                # If only fixed_ip provided, assume enabling
                payload["use_fixedip"] = True
                payload["fixed_ip"] = fixed_ip

            if local_dns_record_enabled is not None:
                payload["local_dns_record_enabled"] = local_dns_record_enabled
                if local_dns_record_enabled and local_dns_record:
                    payload["local_dns_record"] = local_dns_record
                elif not local_dns_record_enabled:
                    payload["local_dns_record"] = ""
            elif local_dns_record is not None:
                # If only local_dns_record provided, assume enabling
                payload["local_dns_record_enabled"] = True
                payload["local_dns_record"] = local_dns_record

            if not payload:
                logger.warning("No IP settings provided for %s", client_mac)
                return False

            api_request = ApiRequest(
                method="put",
                path=f"/rest/user/{client_id}",
                data=payload,
            )
            await self._connection.request(api_request)
            logger.info("IP settings updated for client %s: %s", client_mac, payload)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error setting IP settings for %s: %s", client_mac, e)
            raise
