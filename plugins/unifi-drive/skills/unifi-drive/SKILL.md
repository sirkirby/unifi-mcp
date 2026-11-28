---
name: unifi-drive
description: Read UniFi Drive storage on a UniFi NAS (UNAS) — storage pools, RAID state, disk SMART health and shared drives — and manage its file services and NFS client connections with preview-first writes. Use for NAS capacity, disk health, SMB, NFS or Time Machine, and NFS mounts; use unifi-drive-setup for a missing host or a login failure.
---

# UniFi Drive

## Dependencies

Requires: drive
Optional: none

## The NAS is its own console

This server talks to UniFi Drive on the NAS itself, a separate UniFi OS console
from the gateway, logged in with a local account on that NAS. It is not reached
through the Network application, and its IDs are scoped to the Drive tool
family — do not pass them to Network, Protect or Access tools.

Drive has no startup login. The server starts without contacting the NAS, and
the first tool call logs in, so a running server proves nothing about the host
or password. When the first read fails to log in, stop and use
`unifi-drive-setup`. A server offering only its setup-status tool has no host
configured.

## Discover and read

It provides 22 domain tools, plus 6 meta-tools.
Eighteen domain tools read and four write. In default lazy mode, start with
`drive_tool_index`, filtered by name or search, and request
`include_schemas=True` for the intended tool. Use `drive_execute` with its
`tool` and `arguments` fields when the domain tool is not directly listed.
`drive_batch` runs several calls as jobs, reads side by side and writes one at
a time; `drive_batch_status` and
`drive_batch_cancel` follow and withdraw its jobs, and `drive_load_tools`
loads selected tools for clients that handle tool-list changes.

Read [the tool reference](references/drive-tools.md) for all twenty-two tools
before constructing a call. `drive_list_disks` hides empty bays unless called
with `include_empty=true`. Shared drive IDs from `drive_list_shared_drives` are
what the NFS tools take.

- `drive_list_logs` reads newest first. Pass its `next_cursor` back as `cursor`
  with the same filters for the next page. An unknown category or type is an
  error, not an empty log.
- `drive_get_disk_stats` summarizes each disk over the window. Leave
  `include_samples` off unless per-bucket values are needed: they add about
  12 KB per disk per day.
- `drive_list_snapshots` takes a shared drive's name, not its ID. Scheduled
  snapshots have no name; their `description` (`Scheduled Snapshot`)
  identifies them.
- `drive_list_users` gives each user's access level: owner, admin (any role)
  or user.

## Writes: preview first

Every write previews by default; `confirm=true` applies it. Show the preview,
including its warnings, and confirm only after the user says yes. The plugin's
options keep every write off until the user allows it: turning a file service
on or off and changing an NFS client are updates, adding a client is a create,
and removing one is a delete. A refused write names the variable to set.

- **SMB and Time Machine.** Time Machine runs over SMB, so turning SMB off also
  stops Time Machine backups, and turning Time Machine on while SMB is off is
  refused. Say so before confirming an SMB change.
- **Only shared drives export over NFS.** A personal drive is refused before
  anything is sent; offer a shared drive instead.
- **NFS clients.** Drive keeps every NFS client in one list. Each write changes
  one client, keeps the others exactly as read, and reads the list back. If the
  list changed since the preview, the write stops unsent; preview again. A
  client matching every host (`*`, `0.0.0.0/0`) and `async_writes` (writes lost
  on a power cut) both deserve an explicit yes.
- **NFS off keeps the client list**, so the same clients can mount again when
  NFS comes back on. Remove clients separately if they should not.
- **Outcome.** `mutation_applied: false` means nothing reached the NAS.
  `mutation_applied: null` means the outcome is unknown: read the setting back
  before retrying.

## Coverage and Limitations

Drive has no published API. The server uses the endpoints the Drive web app
uses, checked on one firmware; a field it does not recognize is left out, not
guessed. Name the firmware from `drive_get_system_info` when a result looks
wrong. Report a failed or missing read as unavailable, never as healthy disks
or an empty list. Disk state is what Drive reports at read time, not a
diagnosis.

Nothing here can erase a disk, change a storage pool, or create or delete a
shared drive; the writes change only who can reach the data. There is no
support-bundle tool: for a bug report, give the firmware version and the
failing call by hand.
