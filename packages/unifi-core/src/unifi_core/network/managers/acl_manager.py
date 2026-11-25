"""Manager for MAC ACL rules (Policy Engine) on the UniFi controller.

MAC ACL rules control Layer 2 access within a VLAN by whitelisting
specific MAC address pairs that are allowed to communicate. All
traffic not explicitly allowed is blocked by a default-deny rule.

Requires UniFi Network Application with Policy Engine support.
API endpoint: /proxy/network/v2/api/site/{site}/acl-rules

The official Integration API exposes a separate ACL rule resource
(/v1/sites/{siteId}/acl-rules, UUIDs) with its own ordering endpoint
(/acl-rules/ordering). That resource is disjoint from the V2 MAC ACL
rules here: different IDs, different field shapes, no verified bridge.
The two ordering methods below talk only to the Integration API.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

import aiohttp
from aiounifi.models.api import ApiRequestV2

from unifi_core.auth import UniFiAuth, api_key_variables
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
)
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.operation_gate import write_request_bound
from unifi_core.request_paths import check_request_path, object_id
from unifi_core.tls import CertificateVerificationError, certificate_failure, is_certificate_error

INTEGRATION_API_PAGE_SIZE = 200

logger = logging.getLogger("unifi-network-mcp")


def _missing_key_message(env_prefix: str | None) -> str:
    """Fixed text naming the setting that enables the ACL ordering family.

    The ``UNIFI_*`` variables are named only for a caller that reads them
    (``env_prefix`` set by an MCP server); the API server keeps the key on the
    controller record instead.
    """
    variables = api_key_variables(env_prefix)
    if variables:
        where = f"set {variables}"
    else:
        where = "add it to this controller's configuration"
    return (
        "Network Integration API access requires a UniFi API key. "
        f"Create a Network API token in UniFi Control Plane -> Integrations and {where}."
    )


def _status_error(status: int) -> Exception:
    """Fixed text for a non-2xx integration-API answer; never quotes the response or URL."""
    prefix = f"Network Integration API request failed (HTTP {status})."
    if status == 401:
        return UniFiAuthError(f"{prefix} The controller rejected the configured API key.")
    if status == 403:
        return UniFiPermissionError(f"{prefix} The API key lacks permission for this Integration API resource.")
    if status == 404:
        return UniFiOperationError(
            f"{prefix} The controller does not serve that Integration API endpoint, "
            "or the ACL rule UUID is stale or from another ID family."
        )
    return UniFiOperationError(f"{prefix} The controller refused the request.")


CACHE_PREFIX_ACL_RULES = "acl_rules"


class AclManager:
    """Manages MAC ACL rules on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager, auth: UniFiAuth | None = None):
        self._connection = connection_manager
        self._auth = auth

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

    def _invalidate_cache(self):
        """Invalidate all ACL rule caches."""
        self._connection._invalidate_cache(CACHE_PREFIX_ACL_RULES)

    # ------------------------------------------------------------------
    # Integration API ordering family (UUIDs; disjoint from the V2 rules)
    # ------------------------------------------------------------------

    async def _request_integration_api(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Call the official UniFi Network integration API.

        The integration API rejects local controller cookies for these
        endpoints, so an API key is required. Errors are typed with fixed
        text — the controller's response body, the URL and the exception text
        never reach callers, logs or audits.

        Raises:
            UniFiAuthError: no API key is configured, or the controller rejected it.
            UniFiPermissionError / UniFiOperationError: any other non-2xx answer.
            UniFiMalformedResponseError: the answer is not a JSON object.
        """
        if self._auth is None or not self._auth.has_api_key:
            logger.warning("The ACL ordering family needs a Network API key and none is configured.")
            raise UniFiAuthError(_missing_key_message(getattr(self._connection, "tls_env_prefix", None)))
        # This call bypasses ConnectionManager.request, so the path backstop
        # has to run here before the path reaches the controller URL.
        check_request_path(path)

        base_url = f"https://{self._connection.host}:{self._connection.port}"
        url = f"{base_url}/proxy/network/integration{path}"
        timeout = aiohttp.ClientTimeout(total=10)

        # get_api_key_session() supplies the required X-API-Key header. The
        # integration endpoints reject the local controller cookie session.
        session = await self._auth.get_api_key_session(base_url)

        cert_failure: CertificateVerificationError | None = None
        try:
            # Inside a held write, bounded by what is left of its hold budget;
            # a no-op for reads.
            async with (
                write_request_bound(),
                session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=data,
                    ssl=self._connection.ssl,
                    timeout=timeout,
                    allow_redirects=False,
                ) as resp,
            ):
                if resp.status < 200 or resp.status >= 300:
                    logger.error("Integration API returned %s for %s", resp.status, path)
                    raise _status_error(resp.status)
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    # A write may acknowledge with no body at all; a read must
                    # still carry a JSON object to be usable.
                    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                        return {}
                    raise UniFiMalformedResponseError(
                        "Network Integration API response was not a JSON object."
                    ) from None
                if body is None:
                    return {}
                if not isinstance(body, dict):
                    raise UniFiMalformedResponseError("Network Integration API response was not a JSON object.")
                return body
        except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError):
            raise
        except Exception as e:
            if not is_certificate_error(e):
                raise
            # The certificate error's text names the controller and, for a pin
            # mismatch, both fingerprints. Keep the class and fixed guidance only.
            cert_failure = certificate_failure(e, env_prefix=self._connection.tls_env_prefix)
        finally:
            await session.close()
        # Raised outside the handler, and from None, so no traceback renders the original
        # or an exception a caller is handling. Unreachable without a cert failure:
        # every other error path above re-raised or returned.
        if cert_failure is not None:
            raise cert_failure from None
        raise UniFiOperationError("Network Integration API request failed without a response.")

    async def _get_integration_site_id(self) -> str:
        """Resolve the configured site name/key to the integration API site ID."""
        cache_key = f"integrations_site_id_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if isinstance(cached, str) and cached:
            return cached

        result = await self._request_integration_api("get", "/v1/sites")
        sites = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(sites, list) or not sites:
            return self._connection.site

        configured = self._connection.site
        match = next(
            (
                s
                for s in sites
                if isinstance(s, dict)
                and configured
                in {
                    str(s.get("id", "")),
                    str(s.get("name", "")),
                    str(s.get("key", "")),
                    str(s.get("siteId", "")),
                }
            ),
            None,
        )
        if match is None and len(sites) == 1 and isinstance(sites[0], dict):
            match = sites[0]

        site_id = str((match or {}).get("id") or configured)
        self._connection._update_cache(cache_key, site_id)
        return site_id

    @staticmethod
    def _normalise_ordered_acl_rule_ids(ordered_acl_rule_ids: Any) -> List[str]:
        """Validate the reorder payload shape: non-empty unique UUID strings."""
        if not isinstance(ordered_acl_rule_ids, list) or not ordered_acl_rule_ids:
            raise ValueError("ordered_acl_rule_ids must be a non-empty list of ACL rule IDs")
        if not all(isinstance(rule_id, str) and rule_id for rule_id in ordered_acl_rule_ids):
            raise ValueError("ordered_acl_rule_ids must contain only non-empty ACL rule ID strings")
        duplicates = sorted(rule_id for rule_id, count in Counter(ordered_acl_rule_ids).items() if count > 1)
        if duplicates:
            raise ValueError("Reorder payload contains duplicate ACL rule IDs: %s" % ", ".join(duplicates))
        return list(ordered_acl_rule_ids)

    async def list_integration_acl_rules(self, *, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List the site's MAC ACL rules as the Integration API sees them.

        This is the ID source for the ordering endpoints: the ``id`` values
        here are Integration API UUIDs — the same family the ordering read
        returns and the reorder call accepts. They are a different ID family
        from the V2 controller API's ``_id`` ObjectIDs.

        Args:
            site_id: Optional Integration API site UUID; resolved from the
                configured site when omitted.

        Returns:
            The raw rule list from the controller, across every page.
        """
        resolved_site = site_id or await self._get_integration_site_id()
        path = f"/v1/sites/{object_id(resolved_site, 'site')}/acl-rules"
        rules: List[Dict[str, Any]] = []
        offset = 0
        while True:
            result = await self._request_integration_api(
                "get",
                path,
                data=None,
                params={"limit": str(INTEGRATION_API_PAGE_SIZE), "offset": str(offset)},
            )
            if not isinstance(result, dict) or "data" not in result:
                raise UniFiMalformedResponseError("Controller returned an invalid ACL rule list response")
            page = result.get("data", [])
            if not isinstance(page, list):
                page = []
            page = [rule for rule in page if isinstance(rule, dict)]
            rules.extend(page)

            total_count = result.get("totalCount") if isinstance(result, dict) else None
            if not page or not isinstance(total_count, int) or len(rules) >= total_count:
                break
            offset += len(page)
        return rules

    async def get_acl_rule_ordering(self, *, site_id: Optional[str] = None) -> List[str]:
        """Read user-defined ACL rule ordering from the Integration API.

        Returns:
            The ordered Integration API ACL rule UUIDs as the controller holds
            them. The controller does not document whether this list must be
            complete or whether controller-defined rules participate, so it is
            returned verbatim. Discover the IDs with
            ``list_integration_acl_rules``.
        """
        resolved_site = site_id or await self._get_integration_site_id()
        path = f"/v1/sites/{object_id(resolved_site, 'site')}/acl-rules/ordering"
        result = await self._request_integration_api("get", path)
        ordering = result.get("orderedAclRuleIds") if isinstance(result, dict) else None
        if not isinstance(ordering, list) or not all(isinstance(item, str) for item in ordering):
            raise UniFiMalformedResponseError("Controller returned an invalid ACL rule ordering response")
        return ordering

    async def reorder_acl_rules(
        self,
        ordered_acl_rule_ids: List[str],
        *,
        site_id: Optional[str] = None,
    ) -> List[str]:
        """Reorder user-defined ACL rules on the Integration API.

        Reorder is a live mutation: the current ordering is read fresh from
        the controller immediately before the PUT, and a payload that does not
        preserve the exact current ID multiset is refused. This keeps a stale
        preview or a partial ID list from dropping rules on either dispatch
        surface. Another client can still edit the same controller between
        the fresh read and the PUT; that race is not serialized by this check.

        Args:
            ordered_acl_rule_ids: The full ordered list of Integration API ACL
                rule UUIDs, in the desired order.
            site_id: Optional Integration API site UUID; resolved from the
                configured site when omitted.

        Returns:
            The ordering echoed back by the controller, or the requested
            ordering when the acknowledge carries no response body.
        """
        requested = self._normalise_ordered_acl_rule_ids(ordered_acl_rule_ids)
        resolved_site = site_id or await self._get_integration_site_id()
        path = f"/v1/sites/{object_id(resolved_site, 'site')}/acl-rules/ordering"

        current = await self._request_integration_api("get", path)
        current_ordering = current.get("orderedAclRuleIds") if isinstance(current, dict) else None
        if not isinstance(current_ordering, list) or not all(isinstance(item, str) for item in current_ordering):
            raise UniFiMalformedResponseError("Controller returned an invalid ACL rule ordering response")
        requested_counts = Counter(requested)
        current_counts = Counter(current_ordering)
        if requested_counts != current_counts:
            missing_ids = sorted((current_counts - requested_counts).elements())
            unexpected_ids = sorted((requested_counts - current_counts).elements())
            raise ValueError(
                "Reorder payload must preserve the exact current ACL rule ID set. "
                "Missing: %s; unexpected: %s"
                % (
                    ", ".join(missing_ids) or "none",
                    ", ".join(unexpected_ids) or "none",
                )
            )

        result = await self._request_integration_api("put", path, data={"orderedAclRuleIds": requested})
        ordering = result.get("orderedAclRuleIds") if isinstance(result, dict) else None
        if ordering is None:
            # A 2xx acknowledgement with no body is still an applied mutation.
            return requested
        if not isinstance(ordering, list) or not all(isinstance(item, str) for item in ordering):
            raise UniFiMalformedResponseError("Controller returned an invalid ACL rule ordering response")
        return ordering
