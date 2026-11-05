import ipaddress
import logging
from types import SimpleNamespace
from typing import Any, List, Optional

from aiounifi.models.api import ApiRequest
from aiounifi.models.client import Client

from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError, UniFiOperationError
from unifi_core.mac import canonical_mac, mac_equal, normalize_mac
from unifi_core.network.managers.connection_manager import (
    REST_USER_ROW_CAP,
    ConnectionManager,
    controller_error_code,
    response_status,
)
from unifi_core.request_paths import object_id

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_CLIENTS = "clients"

UNKNOWN_USER_CODE = "api.err.UnknownUser"


class FixedApValidationError(ValueError):
    """Value-free validation failure safe to surface to fixed-AP callers."""


class FixedApAuthError(UniFiAuthError):
    """Fixed guidance for the session-only fixed-AP mutation."""


class FixedApNotFoundError(UniFiOperationError):
    """Identifier-free category for an unavailable fixed-AP target."""


class FixedApOperationError(UniFiOperationError):
    """Identifier-free fixed-AP operation or readback failure."""


class ClientManager:
    """Manages client-related operations on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Client Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_clients(self, include_offline: bool = False) -> List[Client | dict[str, Any]]:
        """Get clients for the current site.

        The default preserves the online-only ``/stat/sta`` contract.  Set
        ``include_offline`` to select the authoritative all/historical client
        path used by public list views without duplicating that branch in each
        application surface.
        """
        if include_offline:
            return await self.get_all_clients()
        if getattr(self._connection, "has_api_key", False) is True:
            await self._connection.initialize()
            if self._connection.integration_inventory_only:
                return await self._connection.public_inventory("clients")
        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_CLIENTS}_online_{self._connection.site}"
        cached_data: Optional[List[Client]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            await self._connection.refresh_handler("clients")
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
                    logger.debug("Raw clients fallback failed: %s", type(fallback_e).__name__)
            self._connection._update_cache(cache_key, clients)
            return clients
        except Exception as e:
            logger.error("Error getting online clients: %s", type(e).__name__)
            raise

    async def get_all_clients(self) -> List[Client]:
        """Get list of all clients (including offline/historical) for the current site."""
        if getattr(self._connection, "has_api_key", False) is True:
            await self._connection.initialize()
            if self._connection.integration_inventory_only:
                from unifi_core.exceptions import UniFiAuthError

                raise UniFiAuthError(
                    "Historical/offline clients require Network session authentication on this controller. "
                    "Use include_offline=false for public connected-client inventory."
                )
        if not await self._connection.ensure_connected() or not self._connection.controller:
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_CLIENTS}_all_{self._connection.site}"
        cached_data: Optional[List[Client]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            await self._connection.refresh_handler("clients_all")
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
                    logger.debug("Raw all-clients fallback failed: %s", type(fallback_e).__name__)
            self._connection._update_cache(cache_key, all_clients)
            return all_clients
        except Exception as e:
            logger.error("Error getting all clients: %s", type(e).__name__)
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

    async def get_client_details(self, client_mac: str, *, existence_only: bool = False) -> Any:
        """Get detailed information for a specific client by MAC address.

        Returns a merged view combining /stat/sta (live data: fresh
        timestamps, uptime, signal, traffic) with /rest/user (stable
        user-table fields: _id, noted, fixed_ip, alias). For currently-
        connected clients, the result has the best of both endpoints; for
        offline clients (not in /stat/sta) it falls back to just /rest/user.

        Each endpoint is queried independently so a transient failure on
        one does not block the lookup. Whenever the /rest/user scan misses a
        MAC-shaped identifier, the authoritative per-MAC GET /stat/user/<mac>
        is consulted (see ``REST_USER_ROW_CAP``). With ``existence_only`` a
        live /stat/sta record is proof enough and the per-MAC request is
        skipped; callers that need ``_id`` leave it off.

        Returns:
            An object with stable ``.mac`` and ``.raw`` attributes so
            callers (rename_client, set_client_ip_settings, etc.) can
            uniformly access the raw payload regardless of which endpoint
            it came from.

        Raises:
            UniFiNotFoundError: The controller reports the MAC unknown, or
                nothing found it.
            UniFiOperationError: The lists missed and the per-MAC lookup
                failed for another reason, so existence is undetermined.
            Original underlying exception: Both list endpoints failed
                (e.g., controller offline), re-raised so callers see the
                real cause instead of a misleading not-found.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        active_record: Optional[Any] = None
        active_error: Optional[Exception] = None
        try:
            active = await self.get_clients()
            for c in active:
                if mac_equal(self._mac_of(c), client_mac):
                    active_record = c
                    break
        except Exception as e:
            active_error = e
            logger.debug("/stat/sta fetch failed during get_client_details: %s", type(e).__name__)

        user_record: Optional[Any] = None
        user_error: Optional[Exception] = None
        try:
            all_clients = await self.get_all_clients()
            for c in all_clients:
                if mac_equal(self._mac_of(c), client_mac):
                    user_record = c
                    break
        except Exception as e:
            user_error = e
            logger.debug("/rest/user fetch failed during get_client_details: %s", type(e).__name__)

        lookup_error: Optional[Exception] = None
        path_mac = canonical_mac(client_mac)
        # A live record already proves existence; only callers that need the
        # user-table fields (``_id``) pay for the per-MAC request then.
        live_is_enough = existence_only and active_record is not None
        if user_record is None and path_mac is not None and not live_is_enough:
            try:
                user_record = await self._get_user_by_mac(path_mac)
            except Exception as e:
                if response_status(e) == 404:
                    # aiounifi raises ResponseError for HTTP 404 and 429 alike;
                    # only the reported status decides (never the URL or body
                    # text). A 404 means the controller does not serve
                    # /stat/user, which is no answer, so the lists' verdict
                    # stands.
                    logger.debug("/stat/user is not served by this controller: %s", type(e).__name__)
                else:
                    lookup_error = e
                    logger.debug("/stat/user lookup failed during get_client_details: %s", type(e).__name__)

        if active_record is None and user_record is None:
            if lookup_error is not None and controller_error_code(lookup_error) == UNKNOWN_USER_CODE:
                # The per-MAC endpoint is authoritative: the controller has no
                # record for this MAC, whatever the list scans did.
                raise UniFiNotFoundError("client", client_mac)
            if active_error is not None and user_error is not None:
                # Both list endpoints failed — surface the underlying
                # connectivity/outage error rather than misreporting it as a
                # not-found.
                raise active_error
            if lookup_error is not None:
                raise UniFiOperationError(
                    f"client '{client_mac}' could not be resolved through the online (/stat/sta) or "
                    f"user (/rest/user, capped at {REST_USER_ROW_CAP} rows) lists, and the per-MAC "
                    f"lookup (/stat/user) failed with {type(lookup_error).__name__}; "
                    "existence could not be determined"
                ) from lookup_error
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

    async def _get_user_by_mac(self, path_mac: str) -> Optional[dict]:
        """Fetch one user-table record via GET /stat/user/<mac>, or ``None`` for an empty list.

        A reply that is not a list of records (a non-JSON page from a proxy or
        a restarting controller decodes to nothing) is a failed lookup, raised
        as :class:`UniFiOperationError` so it is never read as a not-found.
        Controller errors propagate as raised; the caller decides whether
        ``api.err.UnknownUser`` means not-found.
        """
        response = await self._connection.request(
            ApiRequest(method="get", path=f"/stat/user/{object_id(path_mac, 'client MAC')}")
        )
        if not isinstance(response, list) or (response and not isinstance(response[0], dict)):
            raise UniFiOperationError(f"/stat/user reply had unexpected shape {type(response).__name__}")
        if not response:
            logger.debug("/stat/user answered with no record")
            return None
        return response[0]

    async def block_client(self, client_mac: str) -> bool:
        """Block a client by MAC address.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        await self.get_client_details(client_mac, existence_only=True)  # raises on miss
        try:
            # Construct ApiRequest
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "block-sta"},
            )
            # Call the updated request method
            await self._connection.request(api_request)
            logger.info("Block command sent for client [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")  # Invalidate all client caches
            return True
        except Exception as e:
            logger.error("Error blocking client [redacted]: %s", type(e).__name__)
            raise

    async def unblock_client(self, client_mac: str) -> bool:
        """Unblock a client by MAC address.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        await self.get_client_details(client_mac, existence_only=True)  # raises on miss
        try:
            # Construct ApiRequest
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "unblock-sta"},
            )
            # Call the updated request method
            await self._connection.request(api_request)
            logger.info("Unblock command sent for client [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error unblocking client [redacted]: %s", type(e).__name__)
            raise

    async def rename_client(self, client_mac: str, name: str) -> bool:
        """Rename a client device.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        try:
            client = await self.get_client_details(client_mac)  # raises on miss
            if "_id" not in client.raw:
                logger.error("Cannot rename client [redacted]: missing _id in raw payload.")
                return False
            client_id = client.raw["_id"]

            # Use REST endpoint (consistent with set_client_ip_settings).
            # Fall back to legacy /upd/user/ for older standalone controllers.
            try:
                api_request = ApiRequest(
                    method="put", path=f"/rest/user/{object_id(client_id, 'client')}", data={"name": name}
                )
                await self._connection.request(api_request)
            except Exception as e:
                logger.debug(
                    "REST endpoint failed for rename, falling back to legacy /upd/user/ for [redacted]: %s",
                    type(e).__name__,
                )
                api_request = ApiRequest(
                    method="put", path=f"/upd/user/{object_id(client_id, 'client')}", data={"name": name}
                )
                await self._connection.request(api_request)
            logger.info("Rename command sent for client [redacted] to '[redacted]'")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error renaming client [redacted] to '[redacted]': %s", type(e).__name__)
            raise

    async def force_reconnect_client(self, client_mac: str) -> bool:
        """Force a client to reconnect (kick).

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        await self.get_client_details(client_mac, existence_only=True)  # raises on miss
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "kick-sta"},
            )
            await self._connection.request(api_request)
            logger.info("Force reconnect (kick) command sent for client [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error forcing reconnect for client [redacted]: %s", type(e).__name__)
            raise

    async def forget_client(self, client_mac: str) -> bool:
        """Forget a known client: delete its user-table record.

        The controller answers ``forget-sta`` with ``rc: ok`` whether or not
        it removed anything, and a client that appears only in historical
        statistics has no user-table record to remove. So the record is
        looked up per MAC before and after the command, and success means it
        existed and is gone.

        Raises:
            UniFiNotFoundError: The controller has no known-client record for
                the MAC, so nothing was sent.
            UniFiOperationError: The controller still lists the client after
                accepting the command.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        path_mac = canonical_mac(client_mac)
        if path_mac is None or not await self._is_known_client(path_mac):
            raise UniFiNotFoundError(
                "client",
                client_mac,
                f"client '{client_mac}' has no known-client record, so there is nothing to forget. "
                "A client that appears only in historical statistics cannot be removed through this API.",
            )
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"macs": [client_mac], "cmd": "forget-sta"},
            )
            await self._connection.request(api_request)
            logger.info("Forget command sent for client [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
        except Exception as e:
            logger.error("Error forgetting client [redacted]: %s", type(e).__name__)
            raise
        if await self._is_known_client(path_mac):
            raise UniFiOperationError(
                f"the controller accepted the forget command but still lists client '{client_mac}'"
            )
        return True

    async def _user_record(self, path_mac: str) -> Optional[dict]:
        """The controller's user-table record for the MAC, or ``None`` when it has none.

        Reads ``/stat/user/<mac>``; a controller that does not serve it (404) is
        read through the user table itself, uncached. Raises
        :class:`UniFiOperationError` when the answer cannot be established.
        """
        try:
            return await self._get_user_by_mac(path_mac)
        except Exception as e:
            if controller_error_code(e) == UNKNOWN_USER_CODE:
                return None
            if response_status(e) != 404:
                raise
        users = await self._connection.request(ApiRequest(method="get", path="/rest/user"))
        if not isinstance(users, list) or not all(isinstance(user, dict) for user in users):
            raise UniFiOperationError(
                f"/rest/user reply had unexpected shape {type(users).__name__}; "
                "whether the client is known could not be determined"
            )
        record = next((user for user in users if mac_equal(user.get("mac"), path_mac)), None)
        if record is None and len(users) >= REST_USER_ROW_CAP:
            # A full window can leave the record out although the controller keeps it.
            raise UniFiOperationError(
                f"/rest/user returned its {REST_USER_ROW_CAP}-row cap without this client; "
                "whether the client is known could not be determined"
            )
        return record

    async def _is_known_client(self, path_mac: str) -> bool:
        """Whether the controller has a user-table record for the MAC, read per MAC."""
        return await self._user_record(path_mac) is not None

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
        client_mac = normalize_mac(client_mac) or client_mac
        await self.get_client_details(client_mac, existence_only=True)  # raises on miss
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
            logger.info("Authorize command sent for guest [redacted] for %s minutes", minutes)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error authorizing guest [redacted]: %s", type(e).__name__)
            raise

    async def unauthorize_guest(self, client_mac: str) -> bool:
        """Unauthorize (de-authorize) a guest client.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        await self.get_client_details(client_mac, existence_only=True)  # raises on miss
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/stamgr",
                data={"mac": client_mac, "cmd": "unauthorize-guest"},
            )
            await self._connection.request(api_request)
            logger.info("Unauthorize command sent for guest [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error unauthorizing guest [redacted]: %s", type(e).__name__)
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

    @staticmethod
    def _ip_settings_payload(
        use_fixedip: Optional[bool],
        fixed_ip: Optional[str],
        local_dns_record_enabled: Optional[bool],
        local_dns_record: Optional[str],
    ) -> dict:
        """The PUT body for an IP settings change, holding only the fields given."""
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
        return payload

    async def resolve_fixed_ip_network(self, fixed_ip: str, network_id: Optional[str] = None) -> dict[str, str]:
        """Return the configured network a fixed IP reservation belongs to.

        With *network_id*, that network must exist and its subnet must hold the
        address. Without it, exactly one configured network's subnet must hold
        it. A reservation outside its client's network is kept by the
        controller but never applied, and some controllers refuse one without
        a ``network_id`` (``api.err.InvalidNetworkId``).

        Returns:
            ``network_id``, ``name`` and ``subnet`` of the network.

        Raises:
            ValueError: An invalid address, an unknown network, or not exactly
                one network holding the address.
        """
        try:
            address = ipaddress.IPv4Address(str(fixed_ip).strip())
        except ValueError:
            raise ValueError("The fixed IP is not a valid IPv4 address.") from None
        response = await self._connection.request(ApiRequest(method="get", path="/rest/networkconf"))
        records = (
            response if isinstance(response, list) else response.get("data", []) if isinstance(response, dict) else []
        )
        networks = []
        for record in records:
            if not isinstance(record, dict) or not record.get("_id"):
                continue
            try:
                subnet = ipaddress.ip_interface(record["ip_subnet"]).network if record.get("ip_subnet") else None
            except ValueError:
                subnet = None
            networks.append((record, subnet))

        def described(record: dict, subnet: Any) -> dict[str, str]:
            return {"network_id": str(record["_id"]), "name": str(record.get("name") or ""), "subnet": str(subnet)}

        if network_id is not None:
            match = next(((r, s) for r, s in networks if r["_id"] == network_id), None)
            if match is None:
                raise ValueError(f"No network with id {network_id} exists.")
            record, subnet = match
            if subnet is None or address not in subnet:
                raise ValueError(f"The fixed IP is not in network {record.get('name') or network_id!r}'s subnet.")
            return described(record, subnet)
        holding = [(r, s) for r, s in networks if s is not None and address in s]
        if not holding:
            raise ValueError("No configured network contains the fixed IP; check the address or the network's subnet.")
        if len(holding) > 1:
            raise ValueError(f"The fixed IP is in {len(holding)} networks' subnets; pass network_id to choose one.")
        return described(*holding[0])

    async def set_client_ip_settings(
        self,
        client_mac: str,
        use_fixedip: Optional[bool] = None,
        fixed_ip: Optional[str] = None,
        local_dns_record_enabled: Optional[bool] = None,
        local_dns_record: Optional[str] = None,
        network_id: Optional[str] = None,
    ) -> bool:
        """Set fixed IP and/or local DNS record for a client.

        Uses the UniFi REST API endpoint PUT /rest/user/{client_id}.
        Local DNS records require UniFi Network 7.2+.

        A new fixed IP is sent with the ``network_id`` of the network that
        holds it (see :meth:`resolve_fixed_ip_network`). Releasing a fixed IP
        while the client's local DNS record is on is refused unless the same
        call turns the record off, because the controller rejects that release
        (``api.err.LocalDnsRecordRequiresFixedIp``).

        Args:
            client_mac: MAC address of the client to update.
            use_fixedip: Enable (True) or disable (False) fixed IP.
            fixed_ip: The fixed IP address to assign (required if use_fixedip=True).
            local_dns_record_enabled: Enable (True) or disable (False) local DNS.
            local_dns_record: The DNS hostname to assign (e.g., "mydevice.local").
            network_id: Network the fixed IP belongs to; resolved from the
                address when omitted.

        Returns:
            True if the update was successful, False otherwise.

        Raises:
            ValueError: The fixed IP has no single network, or the release
                would leave a local DNS record without a fixed IP.
        """
        client_mac = normalize_mac(client_mac) or client_mac
        try:
            # Get client to find their internal _id; raises UniFiNotFoundError on miss.
            client = await self.get_client_details(client_mac)

            client_raw = client.raw if hasattr(client, "raw") else client
            if "_id" not in client_raw:
                logger.error("Cannot set IP settings for [redacted]: Missing _id")
                return False

            client_id = client_raw["_id"]
            payload = self._ip_settings_payload(use_fixedip, fixed_ip, local_dns_record_enabled, local_dns_record)
            if not payload:
                logger.warning("No IP settings provided for [redacted]")
                return False
            if payload.get("use_fixedip") is True and payload.get("fixed_ip"):
                network = await self.resolve_fixed_ip_network(payload["fixed_ip"], network_id)
                payload["network_id"] = network["network_id"]
            if payload.get("use_fixedip") is False:
                # The controller rejects a release that leaves a local DNS record on
                # (api.err.LocalDnsRecordRequiresFixedIp): check the state this change
                # produces, reading the stored record only when the change leaves DNS alone.
                dns_enabled = payload.get("local_dns_record_enabled")
                if dns_enabled is None:
                    record = await self._user_record(client_mac)
                    dns_enabled = bool((record or {}).get("local_dns_record_enabled"))
                if dns_enabled:
                    raise ValueError(
                        "Releasing the fixed IP would leave a local DNS record enabled, which the controller "
                        "refuses. Pass local_dns_record_enabled=false to turn the record off in the same change, "
                        "or keep the fixed IP."
                    )

            # If client is not "noted" (known), mark it first to enable IP config
            if not client_raw.get("noted"):
                logger.info("Client [redacted] not noted, marking as known first")
                note_payload = {"noted": True}
                if not client_raw.get("name") and client_raw.get("hostname"):
                    note_payload["name"] = client_raw["hostname"]
                try:
                    note_request = ApiRequest(
                        method="put",
                        path=f"/rest/user/{object_id(client_id, 'client')}",
                        data=note_payload,
                    )
                    await self._connection.request(note_request)
                except Exception as note_err:
                    logger.warning("Could not mark client as noted: %s", type(note_err).__name__)

            api_request = ApiRequest(
                method="put",
                path=f"/rest/user/{object_id(client_id, 'client')}",
                data=payload,
            )
            await self._connection.request(api_request)
            logger.info("IP settings updated for client [redacted]: [redacted]")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")
            return True
        except Exception as e:
            logger.error("Error setting IP settings for [redacted]: %s", type(e).__name__)
            raise

    @staticmethod
    def _is_access_point(raw: dict[str, Any]) -> bool:
        """Return whether an adopted legacy device record is an access point."""
        if raw.get("adopted") is not True:
            return False
        if raw.get("is_access_point") is True:
            return True
        device_type = raw.get("type", "")
        if not isinstance(device_type, str) or not device_type.startswith("uap"):
            return False
        return raw.get("is_access_point") is not False

    async def set_client_fixed_ap(
        self,
        client_mac: str,
        fixed_ap_enabled: bool,
        fixed_ap_mac: Optional[str] = None,
    ) -> dict[str, Any]:
        """Pin a wireless client to an access point through its legacy user record.

        The controller accepts this only through the session-authenticated
        ``/rest/user/{id}`` surface. The write starts from a freshly read user
        record, preserving unrelated settings, and verifies the persisted
        fixed-AP state rather than trusting the PUT acknowledgement.
        """
        client_mac = canonical_mac(client_mac)
        ap_mac = canonical_mac(fixed_ap_mac) if fixed_ap_mac is not None else None
        if client_mac is None or (fixed_ap_mac is not None and ap_mac is None):
            raise FixedApValidationError("Client and access point MAC addresses must be valid")
        if fixed_ap_enabled and ap_mac is None:
            raise FixedApValidationError("An access point MAC address is required when enabling fixed AP")

        # API-key-only legacy inventory must never be promoted into a write.
        # ``ensure_connected`` rejects an already-active key route, but can
        # initialize before that check; this dedicated guard never treats a
        # key route as session-authenticated.
        if not await self._connection.ensure_session_connected():
            raise FixedApAuthError(
                "Fixed AP updates require Network session authentication. No client mutation was attempted."
            )

        try:
            client = await self.get_client_details(client_mac)
            initial = self._raw_of(client)
            if initial.get("is_wired") is not False:
                raise FixedApValidationError("Fixed AP requires a client whose wireless connection is verified")

            # /stat/user is the authoritative user record for the legacy PUT;
            # do not mutate a cache or a merged live-client snapshot.
            persisted = await self._get_user_by_mac(client_mac)
            if persisted is None:
                raise UniFiNotFoundError("client", client_mac)
            client_id = persisted.get("_id")
            if not client_id:
                raise FixedApNotFoundError("Fixed AP update requires a persisted client record with an identifier.")

            if fixed_ap_enabled:
                await self._connection.refresh_handler("devices")
                devices = list(self._connection.controller.devices.values())
                access_point = next(
                    (self._raw_of(device) for device in devices if mac_equal(self._mac_of(device), ap_mac)),
                    None,
                )
                if access_point is None or not self._is_access_point(access_point):
                    raise UniFiNotFoundError("access point", ap_mac)

            # Mark a not-yet-noted client as known first, best effort: Network
            # 10.6 keeps the record unnoted yet still honours the fixed AP, and
            # the read-back below is what verifies the outcome. Re-read before
            # the final full-record PUT so that it cannot undo the note.
            if not persisted.get("noted"):
                noted = dict(persisted)
                noted["noted"] = True
                await self._connection.request(
                    ApiRequest(method="put", path=f"/rest/user/{object_id(client_id, 'client')}", data=noted)
                )
                persisted = await self._get_user_by_mac(client_mac)
                if persisted is None:
                    raise FixedApOperationError("Controller did not return the client before fixed AP update")
                if not persisted.get("noted"):
                    logger.info("Controller kept client [redacted] unnoted; continuing with the fixed AP update")

            update = dict(persisted)
            update["fixed_ap_enabled"] = fixed_ap_enabled
            # The controller retains the inactive AP when disabling the pin.
            # Empty-string and null MAC values are rejected on Network 10.6.
            if fixed_ap_enabled:
                update["fixed_ap_mac"] = ap_mac
            await self._connection.request(
                ApiRequest(method="put", path=f"/rest/user/{object_id(client_id, 'client')}", data=update)
            )
            self._connection._invalidate_cache(f"{CACHE_PREFIX_CLIENTS}")

            readback = await self._get_user_by_mac(client_mac)
            if readback is None:
                raise FixedApOperationError("Controller did not return the client after fixed AP update")
            enabled_matches = readback.get("fixed_ap_enabled") is fixed_ap_enabled
            ap_matches = not fixed_ap_enabled or mac_equal(readback.get("fixed_ap_mac"), ap_mac)
            if not enabled_matches or not ap_matches:
                raise FixedApOperationError("Controller did not persist the requested fixed AP settings")
            logger.info("Fixed AP setting updated for client [redacted]")
            return {
                "success": True,
                "fixed_ap_enabled": readback.get("fixed_ap_enabled"),
                "fixed_ap_mac": readback.get("fixed_ap_mac") or None,
            }
        except FixedApNotFoundError:
            raise
        except UniFiNotFoundError:
            raise FixedApNotFoundError(
                "Fixed AP update target was not found. Confirm the client and adopted access point are in this site."
            ) from None
        except (FixedApAuthError, FixedApValidationError, FixedApOperationError):
            raise
        except Exception as exc:
            logger.error("Failed to set fixed AP for client [redacted]: %s", type(exc).__name__)
            raise FixedApOperationError(f"Fixed AP update failed ({type(exc).__name__}).") from None
