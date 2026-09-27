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
from dataclasses import replace
from typing import Any, Dict, List, Optional

from aiounifi.errors import Forbidden, LoginRequired, NoPermission, TwoFaTokenRequired, Unauthorized
from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError, http_status
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.nat import (
    FILTER_SELECTORS,
    OBSERVED_RULE_TYPES,
    RULE_SELECTORS,
    from_controller,
    merge_nat_update,
    nat_update_error,
    nat_verified_update_error,
    normalize_nat_create,
    normalize_nat_update,
    normalize_nat_verified_write,
)
from unifi_core.write_verification import WriteVerificationResult, failed_write, noop_write, verify_write

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_NAT = "nat_rules"
NAT_UNAVAILABLE_HINT = (
    "The controller did not serve the NAT rules endpoint. NAT rules need Network 9.0+ with a UniFi gateway "
    "(zone-based firewall); USG sites and older controllers do not expose them. A wrong site name answers the "
    "same way."
)
_AUTH_ERRORS = (LoginRequired, Forbidden, NoPermission, TwoFaTokenRequired, Unauthorized)
_RETIRED = "<retired>"


class _NatRejected(UniFiOperationError):
    """A definite V2 controller rejection with no response body attached."""


class _NatPreflight(UniFiOperationError):
    """No V2 mutation request was sent because the session was unavailable."""


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

        try:
            connected = await self._connection.ensure_connected()
        except Exception as e:
            logger.error("Error connecting for NAT rules: %s", type(e).__name__)
            _raise_safe_nat_error(e, "list NAT rules")
        if not connected:
            raise UniFiOperationError("Failed to list NAT rules. Check Network session access and permissions.")
        try:
            response = await self._connection.request(ApiRequestV2(method="get", path="/nat"))
        except Exception as e:
            if not isinstance(e, _AUTH_ERRORS) and http_status(e) in (404, 405):
                logger.warning("NAT rules endpoint unavailable: %s", type(e).__name__)
                raise UniFiOperationError(NAT_UNAVAILABLE_HINT) from None
            logger.error("Error listing NAT rules: %s", type(e).__name__)
            _raise_safe_nat_error(e, "list NAT rules")
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
            raise UniFiNotFoundError("nat_rule", "", "NAT rule not found") from None
        return match

    async def create_nat_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a NAT rule and return the stored document.

        Unknown keys, wrong value types and invalid rules raise ``ValueError``
        before any request. ``rule_index`` is assigned as one past the highest
        user-rule index on a fresh list when omitted, since the controller
        rejects a duplicate.
        """
        payload = await self._prepare_create(rule_data, verified=False)

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
        merged = self._prepare_update(current, update, verified=False)

        await self._mutate(ApiRequestV2(method="put", path=f"/nat/{rule_id}", data=merged), "updating")
        return merged

    async def _prepare_create(self, fields: Dict[str, Any], *, verified: bool) -> Dict[str, Any]:
        payload = normalize_nat_verified_write(fields, create=True) if verified else normalize_nat_create(fields)
        if verified:
            # Network 10.6.106's NAT form supplies these on create/save. The
            # controller may omit preference entirely unless it is supplied.
            # They remain caller-read-only and are verified in the readback.
            payload.update(setting_preference="manual", is_predefined=False)
        if "rule_index" not in payload:
            rules = await self.list_nat_rules(refresh=True)
            indexes = (r.get("rule_index") for r in rules if not r.get("is_predefined"))
            payload["rule_index"] = max((i for i in indexes if type(i) is int), default=0) + 1
        return payload

    @staticmethod
    def _prepare_update(current: Dict[str, Any], update: Dict[str, Any], *, verified: bool) -> Dict[str, Any]:
        merged = merge_nat_update(current, update)
        error = nat_verified_update_error(current, merged) if verified else nat_update_error(current, merged)
        if error:
            raise ValueError(error)
        return merged

    @staticmethod
    def _editable(current: Dict[str, Any]) -> bool:
        return current.get("is_predefined") is not True and current.get("setting_preference") == "manual"

    async def preview_nat_update(
        self, rule_id: str, update_data: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Return fresh before/after state for the MCP preview; no write occurs."""
        _check_id(rule_id)
        update = normalize_nat_verified_write(update_data)
        current = await self.get_nat_rule(rule_id, refresh=True)
        if not self._editable(current):
            raise ValueError("Only manual, non-predefined NAT rules can be changed.")
        merged = self._prepare_update(current, update, verified=True)
        if current.get("type") not in OBSERVED_RULE_TYPES and any(
            key in update for key in ("ip_address", "port", "in_interface", "out_interface")
        ):
            raise ValueError("The stored NAT variant has not been verified for public selector edits.")
        for side in ("source_filter", "destination_filter"):
            if side in update and merged.get(side, {}).get("filter_type") not in {"NONE", "ADDRESS_AND_PORT"}:
                raise ValueError("The stored NAT filter variant has not been verified for public selector edits.")
        return current, merged

    async def create_nat_rule_verified(self, rule_data: Dict[str, Any]) -> WriteVerificationResult:
        """Create once, require one controller ID, then verify fresh persisted fields."""
        try:
            payload = await self._prepare_create(rule_data, verified=True)
        except ValueError as error:
            return failed_write(str(error), operation="create")
        except Exception:
            return failed_write("Failed to prepare NAT create; check Network session access.", operation="create")
        try:
            response = await self._mutate(ApiRequestV2(method="post", path="/nat", data=payload), "creating")
        except _NatPreflight:
            return failed_write("NAT create requires Network session access and permissions.", operation="create")
        except _NatRejected as error:
            return failed_write(str(error), operation="create")
        except _AUTH_ERRORS:
            return failed_write("Network session rejected the NAT create request.", operation="create")
        except Exception:
            return _unknown("create")
        created = _rules_from(response)
        if (
            created is None
            or len(created) != 1
            or not isinstance(created[0].get("_id"), str)
            or not created[0]["_id"].strip()
        ):
            return _unknown("create")
        try:
            after = await self.get_nat_rule(created[0]["_id"], refresh=True)
        except Exception:
            return _unknown("create")
        result = verify_write(operation="create", requested=_flat(payload), after=_flat(after))
        return _with_resource(result, after)

    async def update_nat_rule_verified(self, rule_id: str, update_data: Dict[str, Any]) -> WriteVerificationResult:
        """Fetch, validate, merge, PUT once, and compare a fresh readback."""
        try:
            current, merged = await self.preview_nat_update(rule_id, update_data)
        except (ValueError, UniFiNotFoundError) as error:
            return failed_write(str(error), operation="update")
        except Exception:
            return failed_write("Failed to prepare NAT update; check Network session access.", operation="update")
        if merged == current:
            return noop_write(operation="update", resource=from_controller(current).model_dump())
        update = normalize_nat_verified_write(update_data)
        requested = _flat(update)
        requested.update(_retired(current, merged, update))
        try:
            await self._mutate(ApiRequestV2(method="put", path=f"/nat/{rule_id}", data=merged), "updating")
        except _NatPreflight:
            return failed_write("NAT update requires Network session access and permissions.", operation="update")
        except _NatRejected as error:
            return failed_write(str(error), operation="update")
        except _AUTH_ERRORS:
            return failed_write("Network session rejected the NAT update request.", operation="update")
        except Exception:
            return _unknown("update")
        try:
            after = await self.get_nat_rule(rule_id, refresh=True)
        except Exception:
            return _unknown("update")
        result = verify_write(
            operation="update",
            requested=requested,
            before=_verification_view(current, requested),
            after=_verification_view(after, requested),
        )
        return _with_resource(result, after)

    async def toggle_nat_rule_verified(self, rule_id: str, enabled: bool) -> WriteVerificationResult:
        if type(enabled) is not bool:
            return failed_write("enabled must be a boolean.", operation="update")
        return await self.update_nat_rule_verified(rule_id, {"enabled": enabled})

    async def delete_nat_rule_verified(self, rule_id: str) -> WriteVerificationResult:
        try:
            _check_id(rule_id)
            current = await self.get_nat_rule(rule_id, refresh=True)
            if not self._editable(current):
                raise ValueError("Only manual, non-predefined NAT rules can be changed.")
        except (ValueError, UniFiNotFoundError) as error:
            return failed_write(str(error), operation="delete")
        except Exception:
            return failed_write("Failed to prepare NAT delete; check Network session access.", operation="delete")
        try:
            await self._mutate(ApiRequestV2(method="delete", path=f"/nat/{rule_id}"), "deleting")
        except _NatPreflight:
            return failed_write("NAT delete requires Network session access and permissions.", operation="delete")
        except _NatRejected as error:
            return failed_write(str(error), operation="delete")
        except _AUTH_ERRORS:
            return failed_write("Network session rejected the NAT delete request.", operation="delete")
        except Exception:
            return _unknown("delete")
        try:
            rules = await self.list_nat_rules(refresh=True)
        except Exception:
            return _unknown("delete")
        if any(rule.get("_id", rule.get("id")) == rule_id for rule in rules):
            return failed_write(
                "NAT rule remained after delete; inspect the controller before retrying.", operation="delete"
            )
        return WriteVerificationResult(success=True, mutation_applied=True, operation="delete")

    async def _mutate(self, request: ApiRequestV2, verb: str) -> Any:
        """Send a POST/PUT/DELETE and drop the cached list whatever the outcome.

        A reply that never arrives (timeout, gateway error) may still have been
        committed by the controller, so the cached list is invalidated on the
        failure path too; otherwise the next read would serve the old document
        or a deleted rule.
        """
        try:
            try:
                connected = await self._connection.ensure_connected()
            except Exception as error:
                logger.error("Error connecting for NAT mutation: %s", type(error).__name__)
                raise _NatPreflight("Network session access is unavailable.") from None
            if not connected:
                raise _NatPreflight("Network session access is unavailable.")
            return await self._connection.request(request)
        except _NatPreflight:
            raise
        except Exception as e:
            logger.error("Error %s NAT rule: %s", verb, type(e).__name__)
            if not isinstance(e, _AUTH_ERRORS) and http_status(e) in (401, 403):
                raise _NatRejected("Network session rejected the NAT mutation. Check access and permissions.") from None
            if http_status(e) in (400, 409, 422):
                raise _NatRejected("Controller rejected the NAT mutation (HTTP 400/409/422).") from None
            operation = {"creating": "create", "updating": "update", "deleting": "delete"}[verb]
            _raise_safe_nat_error(e, f"{operation} NAT rule")
        finally:
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        self._connection._invalidate_cache(CACHE_PREFIX_NAT)


def _raise_safe_nat_error(error: Exception, operation: str) -> None:
    """Keep controller text and traceback out of HTTP action and audit sinks."""
    kind = type(error).__name__
    if isinstance(error, _AUTH_ERRORS):
        raise type(error)(f"Failed to {operation} ({kind}). Check Network session access and permissions.") from None
    raise UniFiOperationError(
        f"Failed to {operation} ({kind}). Check the controller connection and NAT support."
    ) from None


def _check_id(rule_id: str) -> None:
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError("rule_id must be a nonempty V2 NAT rule ID.")


def _unknown(operation: str) -> WriteVerificationResult:
    return failed_write(
        "NAT mutation outcome is unknown; list rules before deciding whether to retry.",
        operation=operation,
        mutation_applied=None,
    )


def _flat(doc: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in doc.items():
        if key in {"source_filter", "destination_filter"} and isinstance(value, dict):
            result.update({f"{key}.{subkey}": subvalue for subkey, subvalue in value.items()})
        else:
            result[key] = value
    return result


def _retired(current: Dict[str, Any], merged: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    retired: Dict[str, Any] = {}
    if "type" in update:
        for key, _, _ in RULE_SELECTORS:
            if key not in update and current.get(key) and not merged.get(key):
                retired[key] = _RETIRED
    for side in ("source_filter", "destination_filter"):
        if isinstance(update.get(side), dict) and "filter_type" in update[side]:
            old = current.get(side) or {}
            new = merged.get(side) or {}
            for key, _, _ in FILTER_SELECTORS:
                if key not in update[side] and old.get(key) and not new.get(key):
                    retired[f"{side}.{key}"] = _RETIRED
    return retired


def _verification_view(doc: Dict[str, Any], requested: Dict[str, Any]) -> Dict[str, Any]:
    view = _flat(doc)
    for key, value in requested.items():
        if value == _RETIRED and (key not in view or view[key] in (None, [], "")):
            view[key] = _RETIRED
    return view


def _with_resource(result: WriteVerificationResult, resource: Dict[str, Any]) -> WriteVerificationResult:
    return replace(result, resource=from_controller(resource).model_dump())


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
