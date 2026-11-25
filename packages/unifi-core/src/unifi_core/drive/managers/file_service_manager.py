"""File services (SMB, NFS, Time Machine) and NFS client connections.

Writes follow the preview-then-confirm split: a ``plan_*`` method reads the
current state and returns what would change without writing; ``apply_*``
writes it and reads it back. The confirmed methods (``set_file_service``,
``add_nfs_connection``, ``update_nfs_connection``, ``remove_nfs_connection``)
plan again and apply in one call, so the write is built from fresh state
rather than from the preview.

``PUT nfs/advanced-settings`` replaces the whole connection list. Every change
to one client therefore sends every other client exactly as it was read (see
:func:`unifi_core.drive.models.services.connections_for_put`). Two NFS writes
must not interleave, or the second would send a list without the first one's
client. The caller's operation gate runs confirmed writes one at a time; this
module takes no lock of its own. ``apply_nfs_change`` also re-reads the list
just before the ``PUT`` and stops if it changed since the plan, which catches
an edit made in the Drive web UI, or by another process, before that re-read.

A confirmed method whose write's hold budget runs out before the ``PUT`` is
sent raises :class:`~unifi_core.drive.managers.connection_manager.DriveWriteNotSent`:
only reads (and Drive's hostname check, which saves nothing) went out. A
``PUT`` that was sent and never answered raises
:class:`~unifi_core.drive.managers.connection_manager.DriveWriteOutcomeUnknown`.

Known risk: Drive keeps no version on this list, so nothing closes the gap
between that re-read and the ``PUT``. The operation gate covers one server
process, so a write from another process (a second MCP server or the API
server against the same NAS) that lands in that gap is overwritten by this
``PUT``, and neither call reports it. The read-back only catches a write that
lands after this one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from unifi_core.drive.managers.connection_manager import (
    DriveConnectionManager,
    DriveWriteNotSent,
    DriveWriteOutcomeUnknown,
    drive_path,
)
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.drive.models._coerce import as_dict, as_list, text
from unifi_core.drive.models.services import (
    SERVICE_PATHS,
    FileServices,
    NfsConnection,
    NfsConnectionInput,
    NfsSharedDriveAccess,
    connection_for_put,
    connection_to_controller,
    connections_for_put,
    export_path,
    file_services_from_api,
    is_world_client,
    nfs_connection_from_api,
    nfs_connections_from_api,
    validate_client,
)
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiValidationError,
)
from unifi_core.operation_gate import WriteRequestTimeout

logger = logging.getLogger(__name__)

_SERVICE_LABELS = {"smb": "SMB", "nfs": "NFS", "time_machine": "Time Machine"}


@dataclass(frozen=True)
class ServiceChange:
    """A planned file-service toggle."""

    service: str
    enabled_before: bool | None
    enabled_after: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def changes_anything(self) -> bool:
        return self.enabled_before is not self.enabled_after


@dataclass(frozen=True)
class NfsChange:
    """A planned change to one NFS client, and the full list the ``PUT`` will send.

    ``based_on`` is the list the plan was built from, in ``PUT`` shape. The
    write refuses to go ahead if Drive's list no longer matches it.
    """

    action: str  # add | update | remove
    client: str
    before: NfsConnection | None
    after: NfsConnection | None
    connections: list[dict[str, Any]]
    unchanged_clients: list[str]
    based_on: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def _client(value: Any) -> str:
    try:
        return validate_client(value)
    except ValueError as exc:
        raise UniFiValidationError(str(exc)) from None


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()))
    return f"{where}: {first['msg']}" if where else str(first["msg"])


def _same_client(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.strip().casefold() == b.casefold()


def _world_warning(client: str) -> list[str]:
    if not is_world_client(client):
        return []
    return [f"Client {client} matches every host: any machine that can reach the NAS can mount these shared drives."]


def _grant_label(grant: Any) -> str:
    return f"{grant.name or grant.id} {grant.permission or '?'}"


@asynccontextmanager
async def _before_the_change(what: str) -> AsyncIterator[None]:
    """Requests made before a change is sent: a hold budget that runs out here means nothing was changed.

    Drive's hostname check is a ``POST`` that saves nothing, so its unanswered
    request is not a change of unknown outcome either.
    """
    try:
        yield
    except WriteRequestTimeout:
        raise DriveWriteNotSent(
            f"{what}: the write's time budget ran out before the change was sent, so nothing was changed"
        ) from None
    except DriveWriteOutcomeUnknown:
        raise DriveWriteNotSent(
            f"{what}: UniFi Drive did not answer a check made before the change, so nothing was changed"
        ) from None


class FileServiceManager:
    """Reads and changes ``/proxy/drive/api/v1/services/...``."""

    def __init__(self, connection: DriveConnectionManager, shared_drives: SharedDriveManager) -> None:
        self._connection = connection
        self._shared_drives = shared_drives

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _service_settings(self, service: str) -> dict[str, Any]:
        raw = await self._connection.get(drive_path(1, "services", SERVICE_PATHS[service], "settings"))
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError(f"UniFi Drive returned unreadable {_SERVICE_LABELS[service]} settings.")
        return raw

    async def get_file_services(self) -> FileServices:
        smb, nfs, time_machine, settings = await asyncio.gather(
            self._service_settings("smb"),
            self._service_settings("nfs"),
            self._service_settings("time_machine"),
            self._connection.get(drive_path(1, "services", "settings")),
        )
        return file_services_from_api(smb, nfs, time_machine, settings)

    async def _read_nfs_settings(self) -> dict[str, Any]:
        raw = await self._connection.get(drive_path(1, "services", "nfs", "advanced-settings"))
        if not isinstance(raw, dict) or not isinstance(raw.get("connections", []), list):
            raise UniFiMalformedResponseError("UniFi Drive returned unreadable NFS connection settings.")
        return raw

    async def list_nfs_connections(self) -> list[NfsConnection]:
        return nfs_connections_from_api(await self._read_nfs_settings())

    async def check_nfs_hostnames(self, hostnames: list[str]) -> list[dict[str, Any]]:
        """Drive's own check of NFS client names. Returns the entries Drive flagged.

        ``POST nfs/test-hostnames`` writes nothing; the web UI calls it before
        saving a connection and refuses to save when an entry carries an
        ``errorCode``.
        """
        raw = await self._connection.post(
            drive_path(1, "services", "nfs", "test-hostnames"), {"hostnames": list(hostnames)}
        )
        entries = as_dict(raw).get("hostnames")
        if not isinstance(entries, list):
            logger.warning("[drive] NFS hostname check returned an unexpected shape; continuing without it.")
            return []
        return [
            {"hostname": text(entry.get("hostname")), "error_code": entry.get("errorCode")}
            for entry in (as_dict(item) for item in entries)
            if entry.get("errorCode")
        ]

    # ------------------------------------------------------------------
    # File service toggles
    # ------------------------------------------------------------------

    async def plan_set_file_service(self, service: str, enabled: bool) -> ServiceChange:
        if service not in SERVICE_PATHS:
            raise UniFiValidationError("service must be one of: smb, nfs, time_machine")
        current = await self.get_file_services()
        before = {
            "smb": current.smb_enabled,
            "nfs": current.nfs_enabled,
            "time_machine": current.time_machine_enabled,
        }[service]
        warnings: list[str] = []
        if service == "time_machine" and enabled and current.smb_enabled is False:
            raise UniFiValidationError("Time Machine runs over SMB. Enable SMB first.")
        if service == "smb" and not enabled and current.time_machine_enabled:
            warnings.append(
                "Time Machine runs over SMB: turning SMB off turns Time Machine off too, and turning SMB back on "
                "leaves it off. Turn Time Machine on again afterwards (drive_set_file_service)."
            )
        if service == "smb" and enabled and current.time_machine_enabled is False:
            warnings.append("Time Machine stays off; turn it on with drive_set_file_service if it should run.")
        if service == "nfs" and not enabled:
            connections = await self.list_nfs_connections()
            if connections:
                warnings.append(
                    f"NFS clients lose their mounts. The {len(connections)} NFS connection(s) are kept and apply "
                    "again when NFS is turned back on (the Drive web UI clears them instead)."
                )
        if service == "nfs" and enabled and before is not True:
            connections = await self.list_nfs_connections()
            if connections:
                regain = "; ".join(
                    f"{entry.client} ({', '.join(_grant_label(g) for g in entry.shared_drives) or 'no shared drives'})"
                    for entry in connections
                )
                warnings.append(f"These NFS clients can mount again: {regain}.")
        if not enabled:
            warnings.append(f"Clients connected over {_SERVICE_LABELS[service]} are disconnected.")
        return ServiceChange(service=service, enabled_before=before, enabled_after=enabled, warnings=warnings)

    async def set_file_service(self, service: str, enabled: bool) -> tuple[ServiceChange, bool]:
        """Plan from fresh state and write the toggle; returns the plan and the state read back.

        A toggle that changes nothing sends nothing and returns the current state.
        """
        async with _before_the_change(f"Set {_SERVICE_LABELS.get(service, service)}"):
            change = await self.plan_set_file_service(service, enabled)
        if not change.changes_anything:
            return change, change.enabled_after
        return change, await self.apply_set_file_service(change)

    async def apply_set_file_service(self, change: ServiceChange) -> bool:
        """Write the toggle and return the state read back afterwards."""
        path = drive_path(1, "services", SERVICE_PATHS[change.service], "settings")
        await self._connection.put(path, {"enable": change.enabled_after})
        after = as_dict(await self._service_settings(change.service)).get("enable")
        if after is not change.enabled_after:
            raise UniFiOperationError(
                f"UniFi Drive accepted the {_SERVICE_LABELS[change.service]} change, but reading it back shows "
                f"enable={after!r}."
            )
        return after

    # ------------------------------------------------------------------
    # NFS connections
    # ------------------------------------------------------------------

    async def _drive_names(self, grants: list[NfsSharedDriveAccess]) -> dict[str, str | None]:
        """Shared drive id -> name, refusing ids that do not exist."""
        drives = {drive.id: drive.name for drive in await self._shared_drives.list_shared_drives() if drive.id}
        unknown = [grant.id for grant in grants if grant.id not in drives]
        if unknown:
            raise UniFiValidationError(
                f"Unknown shared drive id(s): {', '.join(unknown)}. Use drive_list_shared_drives for valid ids."
            )
        return drives

    @staticmethod
    def _proposed(
        client: str, grants: list[NfsSharedDriveAccess], async_writes: bool, names: dict[str, str | None]
    ) -> NfsConnection:
        return nfs_connection_from_api(
            {
                "client": client,
                "async": async_writes,
                "sharedDrives": [
                    {"id": grant.id, "permission": grant.permission, "name": names.get(grant.id)} for grant in grants
                ],
            }
        )

    async def _nfs_warnings(self, client: str, async_writes: bool) -> list[str]:
        warnings: list[str] = _world_warning(client)
        if (await self._service_settings("nfs")).get("enable") is False:
            warnings.append("NFS is turned off; the connection applies once NFS is enabled (drive_set_file_service).")
        if async_writes:
            warnings.append("Async writes are faster, but writes acknowledged before a power loss can be lost.")
        return warnings

    async def plan_add_nfs_connection(self, connection: NfsConnectionInput) -> NfsChange:
        raw = await self._read_nfs_settings()
        existing = as_list(raw.get("connections"))
        if any(_same_client(as_dict(entry).get("client"), connection.client) for entry in existing):
            raise UniFiValidationError(
                f"NFS client {connection.client} already has a connection. Use drive_update_nfs_connection."
            )
        names = await self._drive_names(connection.shared_drives)
        others = connections_for_put(raw)
        return NfsChange(
            action="add",
            client=connection.client,
            before=None,
            after=self._proposed(connection.client, connection.shared_drives, connection.async_writes, names),
            connections=[*others, connection_to_controller(connection)],
            unchanged_clients=[str(entry.get("client")) for entry in others],
            based_on=connections_for_put(raw),
            warnings=await self._nfs_warnings(connection.client, connection.async_writes),
        )

    async def plan_update_nfs_connection(
        self,
        client: str,
        *,
        shared_drives: list[NfsSharedDriveAccess] | None = None,
        async_writes: bool | None = None,
    ) -> NfsChange:
        client = _client(client)
        if shared_drives is None and async_writes is None:
            raise UniFiValidationError("Nothing to update: pass shared_drives and/or async_writes.")
        raw = await self._read_nfs_settings()
        existing = [entry for entry in as_list(raw.get("connections")) if isinstance(entry, dict)]
        index = next((i for i, entry in enumerate(existing) if _same_client(entry.get("client"), client)), None)
        if index is None:
            raise UniFiNotFoundError("NFS connection", client)
        current = existing[index]
        before = nfs_connection_from_api(current)
        current_put = connection_for_put(current)
        # Grants as read, by drive id, keeping keys this module does not know about.
        current_grants = {str(grant.get("id")): grant for grant in current_put["sharedDrives"]}
        try:
            if shared_drives is None:
                grants = [
                    NfsSharedDriveAccess(id=str(grant.get("id")), permission=grant.get("permission") or "rw")
                    for grant in current_put["sharedDrives"]
                ]
            else:
                # A grant passed without a permission keeps the one the drive already has;
                # only a drive new to this client defaults to rw.
                grants = [
                    grant
                    if "permission" in grant.model_fields_set or grant.id not in current_grants
                    else NfsSharedDriveAccess(
                        id=grant.id, permission=current_grants[grant.id].get("permission") or "rw"
                    )
                    for grant in shared_drives
                ]
            merged = NfsConnectionInput(
                client=str(current.get("client")),
                shared_drives=grants,
                async_writes=bool(current.get("async")) if async_writes is None else async_writes,
            )
        except ValidationError as exc:
            raise UniFiValidationError(f"Invalid NFS connection: {_validation_message(exc)}") from None
        names = await self._drive_names(merged.shared_drives)
        # Keep keys this module does not know about on the edited entry and its grants as well.
        updated = {
            **current_put,
            **connection_to_controller(merged),
            "sharedDrives": [
                {**current_grants.get(grant.id, {}), **grant.to_controller()} for grant in merged.shared_drives
            ],
        }
        connections = connections_for_put(raw)
        connections[index] = updated
        return NfsChange(
            action="update",
            client=merged.client,
            before=before,
            after=self._proposed(merged.client, merged.shared_drives, merged.async_writes, names),
            connections=connections,
            unchanged_clients=[str(entry.get("client")) for i, entry in enumerate(existing) if i != index],
            based_on=connections_for_put(raw),
            warnings=await self._nfs_warnings(merged.client, merged.async_writes),
        )

    async def plan_remove_nfs_connection(self, client: str) -> NfsChange:
        client = _client(client)
        raw = await self._read_nfs_settings()
        existing = [entry for entry in as_list(raw.get("connections")) if isinstance(entry, dict)]
        target = next((entry for entry in existing if _same_client(entry.get("client"), client)), None)
        if target is None:
            raise UniFiNotFoundError("NFS connection", client)
        others = [entry for entry in existing if entry is not target]
        before = nfs_connection_from_api(target)
        mounts = [path for path in (export_path(grant.name) for grant in before.shared_drives) if path]
        return NfsChange(
            action="remove",
            client=str(target.get("client")),
            before=before,
            after=None,
            connections=[connection_for_put(entry) for entry in others],
            unchanged_clients=[str(entry.get("client")) for entry in others],
            based_on=connections_for_put(raw),
            warnings=[f"{client} can no longer mount {', '.join(mounts) or 'any shared drive'} over NFS."],
        )

    async def add_nfs_connection(self, connection: NfsConnectionInput) -> tuple[NfsChange, NfsConnection | None]:
        """Plan from fresh state and write an added client."""
        async with _before_the_change("Add NFS connection"):
            change = await self.plan_add_nfs_connection(connection)
        return change, await self.apply_nfs_change(change)

    async def update_nfs_connection(
        self,
        client: str,
        *,
        shared_drives: list[NfsSharedDriveAccess] | None = None,
        async_writes: bool | None = None,
    ) -> tuple[NfsChange, NfsConnection | None]:
        """Plan from fresh state and write a client's update."""
        async with _before_the_change("Update NFS connection"):
            change = await self.plan_update_nfs_connection(
                client, shared_drives=shared_drives, async_writes=async_writes
            )
        return change, await self.apply_nfs_change(change)

    async def remove_nfs_connection(self, client: str) -> NfsChange:
        """Plan from fresh state and write a client's removal."""
        async with _before_the_change("Remove NFS connection"):
            change = await self.plan_remove_nfs_connection(client)
        await self.apply_nfs_change(change)
        return change

    async def apply_nfs_change(self, change: NfsChange) -> NfsConnection | None:
        """Write the planned list and return the client's connection as read back (``None`` once removed).

        The plan is refused, with nothing written, if Drive's list no longer
        matches the one it was built from.
        """
        async with _before_the_change(f"{change.action.capitalize()} NFS connection"):
            if change.action in ("add", "update"):
                flagged = await self.check_nfs_hostnames([change.client])
                if flagged:
                    codes = ", ".join(str(entry["error_code"]) for entry in flagged)
                    raise UniFiValidationError(f"UniFi Drive rejected NFS client {change.client}: {codes}")
            # Last check before the PUT, which replaces the whole list.
            if connections_for_put(await self._read_nfs_settings()) != change.based_on:
                raise UniFiOperationError(
                    "The NFS connection list changed since this change was planned (another write, or an edit in "
                    "the Drive web UI). Nothing was written; run the change again."
                )
        await self._connection.put(
            drive_path(1, "services", "nfs", "advanced-settings"), {"connections": change.connections}
        )
        after = await self.list_nfs_connections()
        found = next((entry for entry in after if _same_client(entry.client, change.client)), None)
        missing_others = [
            client for client in change.unchanged_clients if not any(_same_client(e.client, client) for e in after)
        ]
        if missing_others:
            raise UniFiOperationError(
                "UniFi Drive accepted the NFS change, but reading it back no longer shows "
                f"{', '.join(missing_others)}. Another write may have changed the list at the same time; "
                "check the NFS settings in the Drive web UI."
            )
        if change.action == "remove":
            if found is not None:
                raise UniFiOperationError(
                    f"UniFi Drive accepted the change, but {change.client} is still listed when read back."
                )
            return None
        if found is None or not _grants_match(found, change.after):
            raise UniFiOperationError(
                f"UniFi Drive accepted the change, but the connection read back for {change.client} does not match it. "
                "Another write may have changed the list at the same time; check the NFS settings in the Drive web UI."
            )
        return found


def _grants_match(found: NfsConnection, expected: NfsConnection | None) -> bool:
    if expected is None:
        return False
    if found.async_writes is not None and found.async_writes != expected.async_writes:
        return False
    return {(g.id, g.permission) for g in found.shared_drives} == {(g.id, g.permission) for g in expected.shared_drives}
