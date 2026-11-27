"""Manager for MAC ACL rules (Policy Engine) on the UniFi controller.

MAC ACL rules control Layer 2 access within a VLAN by whitelisting
specific MAC address pairs that are allowed to communicate. All
traffic not explicitly allowed is blocked by a default-deny rule.

Requires UniFi Network Application with Policy Engine support.
API endpoint: /proxy/network/v2/api/site/{site}/acl-rules
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiNotFoundError, UniFiOperationError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.request_paths import object_id

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_ACL_RULES = "acl_rules"


def _distinct_positions(indices: List[int]) -> List[int]:
    """Keep the chain's sorted ``acl_index`` values, bumping a repeated one past its predecessor.

    The controller stores ``acl_index`` as sent and accepts two rules with the same
    value, whose relative order it does not define. Each position in a rewritten
    chain needs its own value for the read-back to show the requested order.
    """
    positions: List[int] = []
    for index in indices:
        positions.append(index if not positions or index > positions[-1] else positions[-1] + 1)
    return positions


def _chain_records(rules: List[Dict[str, Any]]) -> List[Tuple[str, int, Dict[str, Any]]]:
    """Return ``(rule_id, acl_index, rule)`` for each rule, refusing malformed entries."""
    records: List[Tuple[str, int, Dict[str, Any]]] = []
    for rule in rules:
        rule_id = rule.get("_id")
        index = rule.get("acl_index")
        if not isinstance(rule_id, str) or not rule_id:
            raise UniFiMalformedResponseError("The controller returned an ACL rule without an id.")
        if isinstance(index, bool) or not isinstance(index, int):
            raise UniFiMalformedResponseError("The controller returned an ACL rule without a numeric acl_index.")
        records.append((rule_id, index, rule))
    return records


class AclManager:
    """Manages MAC ACL rules on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def get_acl_rules(self, network_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all MAC ACL rules, optionally filtered by network.

        Args:
            network_id: Optional network ID to filter rules by VLAN.

        Returns:
            List of ACL rule dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_ACL_RULES}_{network_id}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path="/acl-rules")
            response = await self._connection.request(api_request)

            rules = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            if network_id:
                rules = [r for r in rules if r.get("mac_acl_network_id") == network_id]

            self._connection._update_cache(cache_key, rules)
            return rules
        except Exception as e:
            logger.error("Error getting ACL rules: %s", e)
            raise

    async def get_acl_rule_by_id(self, rule_id: str) -> Dict[str, Any]:
        """Get a specific ACL rule by ID.

        Uses list-then-filter because GET /acl-rules/{id} returns 405.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        rules = await self.get_acl_rules()
        match = next((r for r in rules if r.get("_id") == rule_id), None)
        if match is None:
            raise UniFiNotFoundError("acl_rule", rule_id)
        return match

    async def create_acl_rule(self, rule_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new MAC ACL rule.

        Args:
            rule_data: Dictionary containing the ACL rule configuration.
                Required fields:
                - name (str): Rule name
                - acl_index (int): Position in the rule chain
                - action (str): "ALLOW" or "BLOCK"
                - mac_acl_network_id (str): Network ID this rule applies to
                - traffic_source (dict): Source matching config
                - traffic_destination (dict): Destination matching config
                - type (str): "MAC"

        Returns:
            The created ACL rule dictionary, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        required_keys = {"name", "acl_index", "action", "mac_acl_network_id", "type"}
        missing = required_keys - rule_data.keys()
        if missing:
            logger.error("Missing required keys for ACL rule: %s", missing)
            return None

        try:
            api_request = ApiRequestV2(method="post", path="/acl-rules", data=rule_data)
            response = await self._connection.request(api_request)

            self._invalidate_cache()

            if isinstance(response, dict) and "_id" in response:
                return response
            elif isinstance(response, dict) and "data" in response:
                return response["data"]
            elif isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else {"_id": str(response[0])}
            elif response is None or response == "":
                # Some API versions return empty on success — fetch the rule back
                logger.info("Create returned empty response, verifying via list")
                rules = await self.get_acl_rules()
                created = next(
                    (r for r in rules if r.get("name") == rule_data.get("name")),
                    None,
                )
                return created
            else:
                logger.error("Unexpected response creating ACL rule: %s %s", type(response), response)
                return None
        except Exception as e:
            logger.error("Error creating ACL rule: %s", e, exc_info=True)
            raise

    async def update_acl_rule(self, rule_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing MAC ACL rule by merging updates with current state.

        Returns:
            The merged rule dict.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_acl_rule_by_id(rule_id)  # raises on miss
        if not update_data:
            return existing

        merged_data = deep_merge(existing, update_data)
        # Honor the mask-clear sentinel: to_controller_update emits mac_mask=None to
        # mean "remove the mask" (the controller 400s on an empty string, and deep_merge
        # cannot delete a key). Drop any None-valued mac_mask so the PUT omits it entirely.
        # Only touch sides present in update_data — those are fresh dicts from deep_merge's
        # recursion; an untouched side still aliases the cached rule (shallow base.copy()),
        # so popping there could corrupt the in-process cache.
        for side_key in ("traffic_source", "traffic_destination"):
            if side_key not in update_data:
                continue
            side = merged_data.get(side_key)
            if isinstance(side, dict) and side.get("mac_mask", "keep") is None:
                side.pop("mac_mask", None)
        api_request = ApiRequestV2(method="put", path=f"/acl-rules/{object_id(rule_id, 'ACL rule')}", data=merged_data)
        await self._connection.request(api_request)
        self._invalidate_cache()
        return merged_data

    async def delete_acl_rule(self, rule_id: str) -> bool:
        """Delete a MAC ACL rule.

        Args:
            rule_id: The ID of the ACL rule to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequestV2(method="delete", path=f"/acl-rules/{object_id(rule_id, 'ACL rule')}")
            await self._connection.request(api_request)

            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error("Error deleting ACL rule %s: %s", rule_id, e, exc_info=True)
            raise

    async def preview_acl_rule_order(self, network_id: str, ordered_rule_ids: List[str]) -> Dict[str, Any]:
        """Check a chain reorder against a fresh read without writing.

        ``ordered_rule_ids`` must list exactly the IDs currently in the network's
        chain, in the intended order. The chain is read fresh; a stale list or a
        partial one is refused rather than written.

        Raises:
            ValueError: the list does not match the chain read from the controller.
            UniFiMalformedResponseError: a rule has no id or numeric ``acl_index``.
        """
        records = _chain_records(await self._read_acl_rules_fresh(network_id))
        self._check_acl_rule_id_set(ordered_rule_ids, records)
        by_id = {rule_id: rule for rule_id, _index, rule in records}
        current = sorted(records, key=lambda record: (record[1], record[0]))
        return {
            "network_id": network_id,
            "current": [
                {"rule_id": rule_id, "name": rule.get("name", ""), "acl_index": index}
                for rule_id, index, rule in current
            ],
            "requested": [{"rule_id": rule_id, "name": by_id[rule_id].get("name", "")} for rule_id in ordered_rule_ids],
        }

    async def set_acl_rule_order(self, network_id: str, ordered_rule_ids: List[str]) -> Dict[str, Any]:
        """Rewrite a network's ACL rule chain to ``ordered_rule_ids``.

        The list must hold exactly the IDs currently in the chain, in the intended
        order. The chain is read fresh before the write, each rule is sent with
        its full current payload and one of the chain's existing ``acl_index``
        values assigned to its new position, and the order is read back
        afterwards.

        Rewriting a chain takes one PUT per rule, so a controller that rejects an
        intermediate write leaves the earlier rules in their new positions. The
        read-back still runs; the caller should re-read the chain after such a
        failure before retrying.

        Raises:
            ValueError: the list does not match the chain read from the controller.
            UniFiMalformedResponseError: a rule has no id or numeric ``acl_index``.
            UniFiOperationError: the controller reports a different order after
                the write.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        records = _chain_records(await self._read_acl_rules_fresh(network_id))
        self._check_acl_rule_id_set(ordered_rule_ids, records)
        if not ordered_rule_ids:
            return {"network_id": network_id, "ordered_rule_ids": [], "acl_indices": {}}

        by_id = {rule_id: rule for rule_id, _index, rule in records}
        indices = _distinct_positions(sorted(index for _rule_id, index, _rule in records))
        try:
            for rule_id, index in zip(ordered_rule_ids, indices):
                if by_id[rule_id].get("acl_index") == index:
                    continue
                await self._connection.request(
                    ApiRequestV2(
                        method="put",
                        path=f"/acl-rules/{object_id(rule_id, 'ACL rule')}",
                        data=deep_merge(by_id[rule_id], {"acl_index": index}),
                    )
                )
        except Exception as exc:
            self._invalidate_cache()
            logger.error("Error rewriting the ACL rule chain: %s", type(exc).__name__)
            raise
        self._invalidate_cache()

        applied = await self._read_acl_rules_fresh(network_id)
        applied_records = sorted(_chain_records(applied), key=lambda record: (record[1], record[0]))
        actual = [rule_id for rule_id, _index, _rule in applied_records]
        if actual != list(ordered_rule_ids):
            raise UniFiOperationError(
                "The controller accepted the ACL rule order but reports a different chain. "
                "Re-read the current chain before retrying."
            )
        return {
            "network_id": network_id,
            "ordered_rule_ids": actual,
            "acl_indices": {rule_id: index for rule_id, index, _rule in applied_records},
        }

    async def _read_acl_rules_fresh(self, network_id: str) -> List[Dict[str, Any]]:
        """Read the chain straight from the controller, bypassing the cached list."""
        self._invalidate_cache()
        return await self.get_acl_rules(network_id)

    @staticmethod
    def _check_acl_rule_id_set(requested_ids: List[str], records: List[Tuple[str, int, Dict[str, Any]]]) -> None:
        """Refuse a requested order that is not exactly the chain read from the controller."""
        requested = Counter(requested_ids)
        current = Counter(rule_id for rule_id, _index, _rule in records)
        if requested != current:
            raise ValueError(
                "Reorder payload must preserve the exact current ACL rule ID set. Missing: %s; unexpected: %s"
                % (
                    ", ".join(sorted((current - requested).elements())) or "none",
                    ", ".join(sorted((requested - current).elements())) or "none",
                )
            )

    def _invalidate_cache(self):
        """Invalidate all ACL rule caches."""
        self._connection._invalidate_cache(CACHE_PREFIX_ACL_RULES)
