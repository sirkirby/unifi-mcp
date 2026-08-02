"""Visitor management through the official UniFi Access Developer API.

The visitor family is served at ``/api/v1/developer/visitors`` on the
Access API port (default 12445) and requires Bearer-token authentication.
Its UUIDs belong to this Developer API family and are not interchangeable
with IDs from the legacy Access proxy/user surfaces.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError, UniFiNotFoundError

logger = logging.getLogger(__name__)

_VISITORS_PATH = "visitors"
_PAGE_SIZE = 100
_TOKEN_REMEDIATION = (
    "Create a UniFi Access API token and set UNIFI_ACCESS_API_KEY (or UNIFI_API_KEY) for the Access MCP server."
)


class VisitorManager:
    """Reads and mutates the Access Developer API visitor family."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    def _require_developer_api(self, operation: str) -> None:
        """Fail before any proxy fallback when Developer API auth is unavailable."""
        if not self._cm.has_api_key:
            raise UniFiAuthError(f"{operation} requires a UniFi Access API token. {_TOKEN_REMEDIATION}")
        if not self._cm.has_api_client:
            raise UniFiAuthError(
                f"{operation} requires an authenticated UniFi Access Developer API session. "
                f"The configured token did not authenticate. {_TOKEN_REMEDIATION}"
            )

    async def _request(self, method: str, path: str, *, operation: str, **kwargs: Any) -> Any:
        self._require_developer_api(operation)
        return await self._cm.developer_request(method, path, operation=operation, **kwargs)

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        text = str(exc).upper()
        return "HTTP 404" in text or "CODE_NOT_FOUND" in text

    @staticmethod
    def _resolve_names(name: str, first_name: str | None, last_name: str | None) -> tuple[str, str]:
        display_name = name.strip()
        if not display_name:
            raise ValueError("name is required")
        if (first_name is None) != (last_name is None):
            raise ValueError("first_name and last_name must be provided together")
        if first_name is not None and last_name is not None:
            resolved_first = first_name.strip()
            resolved_last = last_name.strip()
            if not resolved_first or not resolved_last:
                raise ValueError("first_name and last_name must not be empty")
            return resolved_first, resolved_last

        parts = display_name.split(maxsplit=1)
        return parts[0], parts[1] if len(parts) == 2 else ""

    @staticmethod
    def _iso_to_epoch(value: str, field_name: str) -> int:
        if not value:
            raise ValueError(f"{field_name} is required")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field_name} must include a timezone")
        return int(parsed.astimezone(timezone.utc).timestamp())

    @staticmethod
    def _resolve_times(
        access_start: str | None,
        access_end: str | None,
        valid_from: str | None,
        valid_until: str | None,
    ) -> tuple[str, str]:
        if access_start and valid_from and access_start != valid_from:
            raise ValueError("access_start and valid_from must match when both are provided")
        if access_end and valid_until and access_end != valid_until:
            raise ValueError("access_end and valid_until must match when both are provided")
        resolved_start = valid_from or access_start
        resolved_end = valid_until or access_end
        if not resolved_start:
            raise ValueError("valid_from (or access_start) is required")
        if not resolved_end:
            raise ValueError("valid_until (or access_end) is required")
        return resolved_start, resolved_end

    @classmethod
    def _developer_create_payload(
        cls,
        name: str,
        access_start: str | None = None,
        access_end: str | None = None,
        *,
        valid_from: str | None = None,
        valid_until: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        company: str | None = None,
        visit_reason: str | None = None,
        remarks: str | None = None,
    ) -> Dict[str, Any]:
        resolved_first, resolved_last = cls._resolve_names(name, first_name, last_name)
        resolved_start, resolved_end = cls._resolve_times(access_start, access_end, valid_from, valid_until)
        start_time = cls._iso_to_epoch(resolved_start, "valid_from")
        end_time = cls._iso_to_epoch(resolved_end, "valid_until")
        if end_time <= start_time:
            raise ValueError("access_end must be after access_start")

        payload: Dict[str, Any] = {
            "first_name": resolved_first,
            "last_name": resolved_last,
            "start_time": start_time,
            "end_time": end_time,
        }
        for key, value in (
            ("email", email),
            ("mobile_phone", phone),
            ("company", company),
            ("visit_reason", visit_reason),
            ("remarks", remarks),
        ):
            if value is not None:
                payload[key] = value
        return payload

    @staticmethod
    def _preview_data(
        name: str,
        access_start: str | None,
        access_end: str | None,
        **extra: Any,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": name,
            "access_start": access_start,
            "access_end": access_end,
        }
        data.update({key: value for key, value in extra.items() if value is not None})
        return data

    @staticmethod
    def _visitor_name(visitor: Dict[str, Any]) -> str | None:
        if visitor.get("name"):
            return str(visitor["name"])
        parts = [str(visitor.get(key, "")).strip() for key in ("first_name", "last_name")]
        return " ".join(part for part in parts if part) or None

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_visitors(self) -> List[Dict[str, Any]]:
        """Return every visitor, following Developer API pagination."""
        visitors: List[Dict[str, Any]] = []
        page_num = 1
        try:
            while True:
                page = await self._request(
                    "GET",
                    _VISITORS_PATH,
                    operation="List visitors",
                    params={"page_num": page_num, "page_size": _PAGE_SIZE},
                )
                if not isinstance(page, list):
                    raise UniFiConnectionError("List visitors failed: unexpected Access API response shape")
                visitors.extend(item for item in page if isinstance(item, dict))
                if len(page) < _PAGE_SIZE:
                    return visitors
                page_num += 1
        except (UniFiAuthError, UniFiConnectionError):
            raise
        except Exception as exc:
            logger.error("Failed to list visitors: %s", exc, exc_info=True)
            raise

    async def get_visitor(self, visitor_id: str) -> Dict[str, Any]:
        """Return one Developer API visitor by its family-scoped UUID."""
        if not visitor_id:
            raise ValueError("visitor_id is required")
        try:
            visitor = await self._request(
                "GET",
                f"{_VISITORS_PATH}/{visitor_id}",
                operation="Get visitor",
            )
            if not isinstance(visitor, dict):
                raise UniFiConnectionError("Get visitor failed: unexpected Access API response shape")
            return visitor
        except UniFiConnectionError as exc:
            if self._is_not_found(exc):
                raise UniFiNotFoundError("visitor", visitor_id) from exc
            raise
        except (UniFiAuthError, UniFiNotFoundError, ValueError):
            raise
        except Exception as exc:
            logger.error("Failed to get visitor %s: %s", visitor_id, exc, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Mutation methods (preview/confirm pattern)
    # ------------------------------------------------------------------

    async def create_visitor(
        self,
        name: str,
        access_start: str | None = None,
        access_end: str | None = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Validate and preview a Developer API visitor creation."""
        self._developer_create_payload(name, access_start, access_end, **extra)
        visitor_data = self._preview_data(name, access_start, access_end, **extra)
        return {
            "visitor_data": visitor_data,
            "proposed_changes": {"action": "create", **visitor_data},
        }

    async def apply_create_visitor(
        self,
        name: str,
        access_start: str | None = None,
        access_end: str | None = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Create a visitor through the Access Developer API."""
        payload = self._developer_create_payload(name, access_start, access_end, **extra)
        try:
            created = await self._request(
                "POST",
                _VISITORS_PATH,
                operation="Create visitor",
                json=payload,
            )
            return {"action": "create", "result": "success", "data": created}
        except (UniFiAuthError, UniFiConnectionError, ValueError):
            raise
        except Exception as exc:
            logger.error("Failed to create visitor: %s", exc, exc_info=True)
            raise

    async def delete_visitor(self, visitor_id: str) -> Dict[str, Any]:
        """Fetch current state and preview a Developer API visitor deletion."""
        if not visitor_id:
            raise ValueError("visitor_id is required")
        current = await self.get_visitor(visitor_id)
        return {
            "visitor_id": visitor_id,
            "visitor_name": self._visitor_name(current),
            "current_state": current,
            "proposed_changes": {"action": "delete"},
        }

    async def apply_delete_visitor(self, visitor_id: str) -> Dict[str, Any]:
        """Revoke a visitor through Developer API DELETE, leaving cancelled history."""
        if not visitor_id:
            raise ValueError("visitor_id is required")
        try:
            await self._request(
                "DELETE",
                f"{_VISITORS_PATH}/{visitor_id}",
                operation="Delete visitor",
            )
            return {"visitor_id": visitor_id, "action": "delete", "result": "success"}
        except UniFiConnectionError as exc:
            if self._is_not_found(exc):
                raise UniFiNotFoundError("visitor", visitor_id) from exc
            raise
        except (UniFiAuthError, UniFiNotFoundError, ValueError):
            raise
        except Exception as exc:
            logger.error("Failed to delete visitor %s: %s", visitor_id, exc, exc_info=True)
            raise
