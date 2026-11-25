"""The NAS's system log, as the Drive UI's System Log page shows it. Read-only."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.models._coerce import as_dict, strings
from unifi_core.drive.models.logs import DriveLogPage, DriveLogQuery, log_entry_from_api
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiValidationError


class DriveLogManager:
    """Reads ``GET /proxy/drive/api/v2/systems/logs`` and the event text from ``systems/log-definitions``."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def list_logs(self, query: DriveLogQuery | None = None) -> DriveLogPage:
        """One page of log entries, newest first.

        ``category`` and ``types`` are checked against the categories and types
        this firmware defines: Drive answers an unknown one with an empty list,
        which would read as "nothing logged". A cursor belongs to the filters it
        was returned with; pass the same filters with it.
        """
        query = query or DriveLogQuery()
        definitions = await self._connection.get(drive_path(2, "systems", "log-definitions"))
        if not isinstance(definitions, dict) or not isinstance(definitions.get("events"), dict):
            raise UniFiMalformedResponseError("UniFi Drive returned unreadable log definitions.")
        types = _resolve_types(query, definitions)
        if types == []:
            return DriveLogPage(entries=[])

        params: dict[str, Any] = {"limit": query.limit}
        if query.severities:
            params["severities"] = ",".join(query.severities)
        if types:
            params["types"] = ",".join(types)
        if query.keyword:
            params["keywords"] = query.keyword
        if query.scope:
            params["scope"] = query.scope
        # Drive reads 0 as a bound, not as "unset", so an unset bound is left out.
        if query.after:
            params["after"] = int(query.after.timestamp())
        if query.before:
            params["before"] = int(query.before.timestamp())
        if query.cursor:
            params["nextToken"] = query.cursor

        raw = await self._connection.get(f"{drive_path(2, 'systems', 'logs')}?{urlencode(params)}")
        if not isinstance(raw, dict) or not isinstance(raw.get("logs"), list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable system log.")
        events = definitions["events"]
        entries = [log_entry_from_api(entry, events) for entry in raw["logs"] if isinstance(entry, dict)]
        token = raw.get("nextToken")
        return DriveLogPage(entries=entries, next_cursor=token if isinstance(token, str) and token else None)


def _resolve_types(query: DriveLogQuery, definitions: dict[str, Any]) -> list[str] | None:
    """The ``types`` filter to send: the asked types, or the category's types; ``None`` for no filter."""
    category_types = as_dict(definitions.get("categoryTypes"))
    known_types = as_dict(definitions.get("types"))
    in_category: list[str] | None = None
    if query.category is not None:
        if query.category not in category_types:
            raise UniFiValidationError(
                f"Unknown log category {query.category!r}. UniFi Drive defines: {', '.join(sorted(category_types))}."
            )
        in_category = strings(category_types[query.category])
    if query.types is None:
        return in_category
    unknown = [name for name in query.types if name not in known_types]
    if unknown:
        raise UniFiValidationError(
            f"Unknown log type {', '.join(map(repr, unknown))}. UniFi Drive defines: {', '.join(sorted(known_types))}."
        )
    if in_category is not None:
        outside = [name for name in query.types if name not in in_category]
        if outside:
            raise UniFiValidationError(
                f"Log type {', '.join(map(repr, outside))} is not in category {query.category!r}, "
                f"which has: {', '.join(in_category)}."
            )
    return list(query.types)
