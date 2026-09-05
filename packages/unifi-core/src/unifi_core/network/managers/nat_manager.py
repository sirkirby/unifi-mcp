"""Manager for NAT rules on the UniFi controller.

NAT rules (DNAT, SNAT, Masquerade) live under the V2 endpoint only; there is
no Integration API equivalent in any Network version.

API endpoint: /proxy/network/v2/api/site/{site}/nat
  GET    /nat        — list all rules
  POST   /nat        — create a rule (rule_index must be unique)
  PUT    /nat/{id}   — replace a rule (full document)
  DELETE /nat/{id}   — delete a rule
There is no GET /nat/{id}; lookups use list + filter.

Zone-based firewall consoles answer this endpoint; a 404/405 on the list means
the site has no UniFi gateway or runs a Network version before 9.0.

Logging here carries operation names and exception class names only: NAT rules
hold addresses and network ids, and controller error text can echo the payload.
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError, http_status
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.nat import (
    merge_nat_update,
    nat_update_error,
    normalize_nat_create,
    normalize_nat_update,
)

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_NAT = "nat_rules"
NAT_UNAVAILABLE_HINT = (
    "The controller did not serve the NAT rules endpoint. NAT rules need Network 9.0+ with a UniFi gateway "
    "(zone-based firewall); USG sites and older controllers do not expose them."
)


class NatManager:
    """Manages NAT rules on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def list_nat_rules(self) -> List[Dict[str, Any]]:
        """Get all NAT rules (cached)."""
        cache_key = f"{CACHE_PREFIX_NAT}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            response = await self._connection.request(ApiRequestV2(method="get", path="/nat"))
        except Exception as e:
            if http_status(e) in (404, 405):
                raise UniFiOperationError(NAT_UNAVAILABLE_HINT) from e
            logger.error("Error listing NAT rules: %s", type(e).__name__)
            raise
        rules = _as_list(response)
        self._connection._update_cache(cache_key, rules)
        return rules

    async def get_nat_rule(self, rule_id: str) -> Dict[str, Any]:
        """Get one NAT rule by id (list + filter; the endpoint has no GET by id).

        Raises:
            UniFiNotFoundError: If no rule has that id.
        """
        rules = await self.list_nat_rules()
        match = next((r for r in rules if r.get("_id", r.get("id")) == rule_id), None)
        if match is None:
            raise UniFiNotFoundError("nat_rule", rule_id)
        return match

    async def create_nat_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a NAT rule.

        Unknown keys and invalid rules raise ``ValueError`` before any request.
        ``rule_index`` is assigned as one past the highest existing index when
        omitted, since the controller rejects a duplicate.
        """
        payload = normalize_nat_create(rule_data)
        if "rule_index" not in payload:
            existing = (r.get("rule_index") for r in await self.list_nat_rules())
            payload["rule_index"] = max((i for i in existing if isinstance(i, int)), default=0) + 1

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            response = await self._connection.request(ApiRequestV2(method="post", path="/nat", data=payload))
        except Exception as e:
            logger.error("Error creating NAT rule: %s", type(e).__name__)
            raise
        self._invalidate_cache()
        created = _as_list(response)
        return created[0] if created else response

    async def update_nat_rule(self, rule_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a NAT rule by merging a partial update over the stored rule and PUTting it back.

        Selectors the update deactivates are dropped, and only errors the
        update introduces are reported (``ValueError``).

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        update = normalize_nat_update(update_data)
        current = await self.get_nat_rule(rule_id)
        return await self._put_update(rule_id, current, update)

    async def delete_nat_rule(self, rule_id: str) -> bool:
        """Delete a NAT rule. Returns True on success; controller errors propagate."""
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            await self._connection.request(ApiRequestV2(method="delete", path=f"/nat/{rule_id}"))
        except Exception as e:
            logger.error("Error deleting NAT rule: %s", type(e).__name__)
            raise
        self._invalidate_cache()
        return True

    async def toggle_nat_rule(self, rule_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Enable or disable a NAT rule; flips the stored state when ``enabled`` is omitted."""
        current = await self.get_nat_rule(rule_id)
        if enabled is None:
            enabled = not current.get("enabled", False)
        return await self._put_update(rule_id, current, {"enabled": enabled})

    async def _put_update(self, rule_id: str, current: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        if not update:
            return current
        merged = merge_nat_update(current, update)
        if error := nat_update_error(current, merged):
            raise ValueError(error)

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            await self._connection.request(ApiRequestV2(method="put", path=f"/nat/{rule_id}", data=merged))
        except Exception as e:
            logger.error("Error updating NAT rule: %s", type(e).__name__)
            raise
        self._invalidate_cache()
        return merged

    def _invalidate_cache(self) -> None:
        self._connection._invalidate_cache(CACHE_PREFIX_NAT)


def _as_list(response: Any) -> List[Dict[str, Any]]:
    """Accept a bare list or a ``{"data": [...]}`` envelope; wrap a bare object."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        data = response.get("data")
        return data if isinstance(data, list) else [response]
    return []
