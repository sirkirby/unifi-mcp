"""Manager for NAT rules on the UniFi controller.

NAT rules (DNAT, SNAT, Masquerade) live under the V2 endpoint only; there is
no Integration API equivalent in any Network version.

API endpoint: /proxy/network/v2/api/site/{site}/nat
  GET    /nat        — list all rules
  POST   /nat        — create a rule (rule_index must be unique)
  PUT    /nat/{id}   — replace a rule (full document)
  DELETE /nat/{id}   — delete a rule
There is no GET /nat/{id}; lookups use list + filter, and every per-id method
resolves the id against the list before sending it, so the path segment is
always a controller-issued id.

Zone-based firewall consoles answer this endpoint; a 404/405 on the list, or a
body the client cannot decode, means the site has no UniFi gateway or runs a
Network version before 9.0.

This module's own logger calls carry operation names and exception class names
only: NAT rules hold addresses and network ids, and controller error text can
echo the payload. The connection layer below logs on its own terms.
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.errors import Forbidden, LoginRequired, NoPermission, TwoFaTokenRequired, Unauthorized
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
    "(zone-based firewall); USG sites and older controllers do not expose them. A wrong site name answers the "
    "same way."
)
_AUTH_ERRORS = (LoginRequired, Forbidden, NoPermission, TwoFaTokenRequired, Unauthorized)


class NatManager:
    """Manages NAT rules on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def list_nat_rules(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Get all NAT rules (cached unless ``refresh``)."""
        cache_key = f"{CACHE_PREFIX_NAT}_{self._connection.site}"
        cached = None if refresh else self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            response = await self._connection.request(ApiRequestV2(method="get", path="/nat"))
        except Exception as e:
            if not isinstance(e, _AUTH_ERRORS) and http_status(e) in (404, 405):
                logger.warning("NAT rules endpoint unavailable: %s", type(e).__name__)
                raise UniFiOperationError(NAT_UNAVAILABLE_HINT) from e
            logger.error("Error listing NAT rules: %s", type(e).__name__)
            raise
        rules = _rules_from(response)
        if rules is None:
            logger.warning("NAT rules endpoint returned no decodable data")
            raise UniFiOperationError(NAT_UNAVAILABLE_HINT)
        self._connection._update_cache(cache_key, rules)
        return rules

    async def get_nat_rule(self, rule_id: str, *, refresh: bool = False) -> Dict[str, Any]:
        """Get one NAT rule by id (list + filter; the endpoint has no GET by id).

        ``refresh`` bypasses the cached list. Every mutation reads the rule this
        way: PUT replaces the whole document, so a replacement built from a
        cached copy would undo any change made outside this process since the
        list was cached (an operator disabling the rule, a moved address).

        Raises:
            UniFiNotFoundError: If no rule has that id.
        """
        rules = await self.list_nat_rules(refresh=refresh)
        match = next((r for r in rules if r.get("_id", r.get("id")) == rule_id), None)
        if match is None:
            raise UniFiNotFoundError("nat_rule", rule_id)
        return match

    async def create_nat_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a NAT rule and return the stored document.

        Unknown keys, wrong value types and invalid rules raise ``ValueError``
        before any request. ``rule_index`` is assigned as one past the highest
        user-rule index on a fresh list when omitted, since the controller
        rejects a duplicate.
        """
        payload = normalize_nat_create(rule_data)
        if "rule_index" not in payload:
            rules = await self.list_nat_rules(refresh=True)
            indexes = (r.get("rule_index") for r in rules if not r.get("is_predefined"))
            payload["rule_index"] = max((i for i in indexes if isinstance(i, int)), default=0) + 1

        response = await self._mutate(ApiRequestV2(method="post", path="/nat", data=payload), "creating")
        created = _rules_from(response)
        if not created:
            logger.warning("NAT rule create returned no decodable data")
            raise UniFiOperationError(
                "The controller answered the NAT rule create without a rule document; the rule may have been "
                "created. List the rules before retrying."
            )
        return created[0]

    async def update_nat_rule(self, rule_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a NAT rule by merging a partial update over the stored rule and PUTting it back.

        Selectors the update deactivates are dropped, and only errors the
        update introduces are reported (``ValueError``).

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        update = normalize_nat_update(update_data)
        current = await self.get_nat_rule(rule_id, refresh=True)
        return await self._put_update(rule_id, current, update)

    async def delete_nat_rule(self, rule_id: str) -> bool:
        """Delete a NAT rule. Returns True on success; controller errors propagate.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        await self.get_nat_rule(rule_id)  # resolves the id; nothing is built from the document
        await self._mutate(ApiRequestV2(method="delete", path=f"/nat/{rule_id}"), "deleting")
        return True

    async def toggle_nat_rule(self, rule_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Enable or disable a NAT rule; flips the controller's current state when ``enabled`` is omitted."""
        current = await self.get_nat_rule(rule_id, refresh=True)
        if enabled is None:
            enabled = not current.get("enabled", False)
        return await self._put_update(rule_id, current, {"enabled": enabled})

    async def _put_update(self, rule_id: str, current: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        if not update:
            return current
        merged = merge_nat_update(current, update)
        if error := nat_update_error(current, merged):
            raise ValueError(error)

        await self._mutate(ApiRequestV2(method="put", path=f"/nat/{rule_id}", data=merged), "updating")
        return merged

    async def _mutate(self, request: ApiRequestV2, verb: str) -> Any:
        """Send a POST/PUT/DELETE and drop the cached list whatever the outcome.

        A reply that never arrives (timeout, gateway error) may still have been
        committed by the controller, so the cached list is invalidated on the
        failure path too; otherwise the next read would serve the old document
        or a deleted rule.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            return await self._connection.request(request)
        except Exception as e:
            logger.error("Error %s NAT rule: %s", verb, type(e).__name__)
            raise
        finally:
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        self._connection._invalidate_cache(CACHE_PREFIX_NAT)


def _rules_from(response: Any) -> Optional[List[Dict[str, Any]]]:
    """Rule documents from a bare list, a ``{"data": [...]}`` envelope or a bare object; ``None`` otherwise.

    The connection layer hands back ``None`` when the body was not JSON (an
    error page, a login redirect), which must not read as "no rules".
    """
    data = response.get("data", response) if isinstance(response, dict) else response
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list) and all(isinstance(r, dict) for r in data):
        return data
    return None
