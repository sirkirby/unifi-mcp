"""A synthetic UniFi Drive NAS behind the real ``DriveConnectionManager``.

Only the connection manager's transport (``_send``) is replaced, so its login,
envelope unwrapping, error mapping and write-budget handling run for real, as
do the domain managers above it. The NAS keeps the file-service toggles and the
NFS connection list as state, so a confirmed write can be read back.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from unifi_core.drive.managers.connection_manager import DriveConnectionManager
from unifi_core.exceptions import UniFiConnectionError

from tests.innerspace_data import bootstrap as _bootstrap

V1 = "/proxy/drive/api/v1"
V2 = "/proxy/drive/api/v2"
NFS_SETTINGS = f"{V1}/services/nfs/advanced-settings"
HOSTNAME_CHECK = f"{V1}/services/nfs/test-hostnames"

POOL_ID = "11111111-1111-4111-8111-111111111111"
RAID_GROUP_ID = "aaaaaaaa:bbbbbbbb:cccccccc:dddddddd"
DRIVE_ID = "22222222-2222-4222-8222-222222222222"
OTHER_DRIVE_ID = "33333333-3333-4333-8333-333333333333"
PERSONAL_DRIVE_ID = "44444444-4444-4444-8444-444444444444"
MISSING_DRIVE_ID = "55555555-5555-4555-8555-555555555555"
CLIENT = "192.0.2.76"
OTHER_CLIENT = "192.0.2.77"
NEW_CLIENT = "192.0.2.78"
NAS_HOST = "192.0.2.20"
BIG_CAPACITY = 15992168120320  # past GraphQL's 32-bit Int


def _slot(slot: str, **disk: Any) -> dict[str, Any]:
    empty = {
        "slotId": slot,
        "poolId": "",
        "raidGroupId": "",
        "type": "",
        "state": "empty",
        "model": "",
        "size": 0,
        "serial": "",
        "riskReasons": [],
        "incompatibleReasons": [],
    }
    return {**empty, **disk}


STORAGE = {
    "pools": [
        {
            "number": 1,
            "id": POOL_ID,
            "preferLevel": "raid5",
            "type": "lvm",
            "status": "noDataProtectionYet",
            "capacity": BIG_CAPACITY,
            "usage": 146655412224,
            "activeRaidGroupId": RAID_GROUP_ID,
            "raidGroups": [
                {
                    "number": 1,
                    "id": RAID_GROUP_ID,
                    "isSSDCache": False,
                    "currentLevel": "raid1",
                    "configLevel": "raid5",
                    "currentProtection": 0,
                    "expectedProtection": 1,
                    "recommendedDiskSize": 16000900661248,
                }
            ],
            "initializingStatus": "successful",
        }
    ],
    "disks": [
        _slot(
            "1",
            poolId=POOL_ID,
            raidGroupId=RAID_GROUP_ID,
            type="HDD",
            state="optimal",
            model="Synthetic HDD",
            size=16000900661248,
            serial="SYNTHETIC-SERIAL-1",
            temperature=33,
            powerOnHours=15592,
        ),
        _slot("2"),
    ],
    "cacheSlots": [_slot("1")],
}

DRIVES = {
    "drives": [
        {
            "id": DRIVE_ID,
            "type": "shared",
            "name": "Shared_Drive",
            "status": "active",
            "storagePoolId": POOL_ID,
            "quota": -1,
            "usage": 145307009024,
            "role": "admin",
            "protections": {"encryptionStatus": "unencrypted", "remoteBackupEnabled": False, "snapshotEnabled": False},
            "memberCount": 2,
        },
        {
            "id": OTHER_DRIVE_ID,
            "type": "shared",
            "name": "Media",
            "status": "active",
            "storagePoolId": POOL_ID,
            "quota": 1099511627776,
            "usage": 0,
            "role": "admin",
            "protections": {"encryptionStatus": "unencrypted", "remoteBackupEnabled": False, "snapshotEnabled": True},
            "memberCount": 1,
        },
        {"id": PERSONAL_DRIVE_ID, "type": "personal", "name": "home", "status": "active", "storagePoolId": POOL_ID},
    ]
}

SYSTEM = {
    "name": "Synthetic NAS",
    "hostname": "synthetic-nas",
    "mac": "00005E005302",
    "isSetup": True,
    "deviceState": "updateAvailable",
    "uptime": 5269.06,
    "cpu": {"currentload": 0.169, "temperature": 64},
    "memory": {"total": 16639296, "available": 13053120},
    "hardware": {"name": "UniFi Network Attached Storage Pro 8", "shortname": "UNASPRO8", "firmwareVersion": "5.0.12"},
    "publicIp": "198.51.100.1",
    "devices": {"unifiOS": [{"mac": "00005E005302", "updateAvailable": "5.0.17", "source": "self"}]},
    # The Drive application reports its own version here, apart from UniFi OS.
    "apps": {
        "controllers": [
            {"name": "network", "version": "10.0.0"},
            {"name": "drive", "version": "4.4.31", "updateAvailable": "4.5.7", "isRunning": True},
        ]
    },
}

SERVICE_SETTINGS = {
    "customDomain": "",
    "networkInterfaces": [
        {
            "interface": "ethernet",
            "interfaceName": "enp0s0",
            "connected": True,
            "maxSpeed": "10 GbE",
            "linkSpeed": "10 GbE",
            "address": NAS_HOST,
            "mac": "00:00:5e:00:53:01",
        }
    ],
}


# System log, shaped as UniFi OS 6.0.18 / Drive 4.4.31 answers it; names, addresses and ids are synthetic.
LOG_CURSOR = "synthetic-next-page"
LOGS = {
    "logs": [
        {
            "id": "66666666-6666-4666-8666-666666666666",
            "category": "storage",
            "type": "storagePool",
            "name": "StoragePoolArrayAtRiskSingleV1",
            "severity": "very_high",
            "data": {"storagePool": "Storage Pool 1", "drive": "Bay 3"},
            "panels": {},
            "createdAt": "2026-11-20T10:00:00.000000-05:00",
        },
        {
            "id": "77777777-7777-4777-8777-777777777777",
            "category": "storage",
            "type": "drive",
            "name": "DriveInsertedV1",
            "severity": "low",
            "data": {"drive": "Bay 1"},
            "panels": {"drive": {"data": {"type": "hardDrive", "data": {"id": "1"}}}},
            "createdAt": "2026-11-18T14:57:11.757183-05:00",
        },
    ]
}
LOG_DEFINITIONS = {
    "categories": {"activity": "Activity", "settings": "Settings", "storage": "Storage"},
    "types": {"drive": "Drive", "fanMode": "Fan Mode", "storagePool": "Storage Pool", "userAccess": "User Access"},
    "categoryTypes": {"activity": ["userAccess"], "settings": ["fanMode"], "storage": ["storagePool", "drive"]},
    "events": {
        "StoragePoolArrayAtRiskSingleV1": {
            "title": "Storage Pool Array at Risk",
            "description": "{storagePool} is degraded. {drive} is showing pre-failure indicators.",
        },
        "DriveInsertedV1": {"title": "Drive Inserted", "description": "{drive} was inserted and is ready to use."},
    },
}

# Pool usage keyed by pool id, as storage/usage answers it.
STORAGE_USAGE = {
    POOL_ID: {
        "poolId": POOL_ID,
        "used": 10826060070912,
        "available": 5166108049408,
        "capacity": BIG_CAPACITY,
        "usedByPersonalDrives": 0,
        "usedBySharedDrives": 10825012379648,
        "usedByM365": 0,
    }
}

NETWORK_IO = {"receiveKBPS": 6.319893, "transmitKBPS": 17.447551, "timestamp": "2026-01-02T03:04:05.123456789-05:00"}
FAN_CONTROL = {"availableProfiles": ["cooling", "default", "quiet"], "currentProfile": "default"}
# Two 15-minute buckets for one bay and the cache slot, which has no data.
DISK_STATS = {
    "series": {
        "disks": [
            {
                "slotId": "1",
                "type": "HDD",
                "serial": "SYNTHETIC-SERIAL-1",
                "temperatures": [34, 36],
                "readKBPS": [100.5, 300.25],
                "writeKBPS": [0, 50],
                "badSectorCount": [0, 2],
            }
        ],
        "cacheSlots": [
            {
                "slotId": "1",
                "type": "SSD",
                "temperatures": [None, None],
                "readKBPS": [None, None],
                "writeKBPS": [None, None],
                "badSectorCount": [None, None],
            }
        ],
    },
    "window": {"samples": 2, "start": 1767225600, "end": 1767227400, "interval": 900},
}

SMB_ADVANCED = {"personalDriveRecycleEnabled": True, "personalDriveRecycleStatus": "optimal"}
RSYNC_PASSWORD = "synthetic-rsync-password"
RSYNC = {"enable": True, "rsyncAccount": {"username": "backup", "password": RSYNC_PASSWORD}}
SYSTEMS_INFO = {"sshEnabled": False, "remoteAccessEnabled": False, "firmwareVersion": "6.0.18"}

USER_ID = "99999999-9999-4999-8999-999999999999"
SNAPSHOT_OVERVIEW = {
    "personal": [
        {
            "coverageSize": BIG_CAPACITY,
            "deletionCount": 0,
            "lastSnapshotTime": "2026-01-02T03:00:00Z",
            "lockedCount": 1,
            "maxCount": 10,
            "nextSnapshotTime": "2026-01-03T03:00:00Z",
            "paused": False,
            "restoringDrive": False,
            "schedule": {
                "interval": 60,
                "weekdays": "",
                "monthdays": "1,15,L",
                "firstRunTime": "3:00",
                "lastRunTime": "3:00",
                "enable": True,
            },
            "settingId": "setting-personal-1",
            "user": {"id": USER_ID, "firstName": "Synthetic", "lastName": "Person"},
            "encryptionStatus": "unencrypted",
            "totalCount": 3,
        }
    ],
    "shared": [
        {
            "coverageSize": 0,
            "deletionCount": 0,
            "lastSnapshotTime": None,
            "lockedCount": 0,
            "maxCount": 0,
            "nextSnapshotTime": None,
            "paused": True,
            "pauseReason": "ErrSnapshotStorageLow",
            "restoringDrive": False,
            "schedule": {
                "interval": 0,
                "weekdays": "",
                "monthdays": "",
                "firstRunTime": "",
                "lastRunTime": "",
                "enable": False,
            },
            "settingId": None,
            "sharedDrive": {"id": OTHER_DRIVE_ID, "name": "Media", "status": "active"},
            "totalCount": 0,
        }
    ],
}
SNAPSHOTS = {
    "Media": [
        {
            "id": "snap-2",
            "name": "",
            "description": "Scheduled Snapshot",
            "createdAt": "2026-01-02T03:00:00Z",
            "locked": True,
        },
        {"id": "snap-1", "name": "before upgrade", "createdAt": "2026-01-01T03:00:00Z", "locked": False},
    ],
    "Shared_Drive": [],
}

USERS = [
    {
        "id": USER_ID,
        "username": "owner",
        "fullName": "Synthetic Owner",
        "email": "owner@example.com",
        "status": "active",
        "isOwner": True,
        "roles": [{"level": 1, "systemKey": "owner"}],
        "appliedStorageProfile": {"enable": True, "id": "profile-1"},
        "mustChangePassword": False,
        "linkedToAD": False,
        "hasUniFiSsoId": False,
        "createdAt": "2026-01-01T00:00:00+00:00",
        "lastLogin": "2026-01-02T03:04:05+00:00",
        "avatar": "https://192.0.2.10/avatar/synthetic.png",
        "ssoId": "sso-synthetic",
    },
    {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "username": "member",
        "fullName": "Synthetic Member",
        "email": "",
        "status": "deactivated",
        "isOwner": False,
        "roles": [],
        "lastLogin": "1970-01-01T00:00:00Z",
    },
]
GROUP_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
GROUPS = {"groups": [{"id": GROUP_ID, "name": "Family", "unknownField": 1}]}


def connection(client: str, *grants: tuple[str, str, str], async_writes: bool = False) -> dict[str, Any]:
    """A connection as Drive returns it on read; ``grants`` are ``(id, name, permission)``."""
    return {
        "client": client,
        "async": async_writes,
        "errorCodes": [],
        "sharedDrives": [
            {"id": gid, "name": name, "status": "active", "encryptionStatus": "unencrypted", "permission": perm}
            for gid, name, perm in grants
        ],
    }


def _envelope(data: Any) -> dict[str, Any]:
    return {"err": None, "type": "single", "data": data}


@dataclass
class FakeDrive:
    """Answers the Drive endpoints the managers use; writes change its state."""

    services: dict[str, bool] = field(default_factory=lambda: {"smb": True, "nfs": True, "time-machine": False})
    connections: list[dict[str, Any]] = field(
        default_factory=lambda: [
            connection(CLIENT, (DRIVE_ID, "Shared_Drive", "rw")),
            connection(OTHER_CLIENT, (OTHER_DRIVE_ID, "Media", "ro")),
        ]
    )
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    # (method, path) -> HTTP status to answer instead, or an exception to raise as the transport failure.
    faults: dict[tuple[str, str], Any] = field(default_factory=dict)
    login_status: int = 200

    @property
    def changes(self) -> list[tuple[str, str, Any]]:
        """Requests that would change the NAS: every write except the login and the hostname check."""
        return [
            (method, path, body)
            for method, path, body in self.requests
            if method in ("PUT", "PATCH", "DELETE") and not path.startswith("/api/auth")
        ]

    def _grant_names(self, grants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        names = {drive["id"]: drive["name"] for drive in DRIVES["drives"]}
        return [
            {**grant, "name": names.get(grant.get("id")), "status": "active", "encryptionStatus": "unencrypted"}
            for grant in grants
        ]

    async def send(
        self, method: str, path: str, url: Any, json_body: Any, *, csrf: bool = True
    ) -> tuple[int, dict[str, str], Any]:
        self.requests.append((method, path, copy.deepcopy(json_body)))
        fault = self.faults.get((method, path))
        if isinstance(fault, BaseException):
            raise fault
        if isinstance(fault, int):
            return fault, {}, {"err": {"msg": "synthetic failure"}}
        if (method, path) == ("POST", "/api/auth/login"):
            if self.login_status != 200:
                return self.login_status, {}, None
            return 200, {"x-csrf-token": "csrf-1"}, {}
        if (method, path) == ("POST", "/api/auth/logout"):
            return 200, {}, {}
        if (method, path) == ("GET", "/api/system"):
            return 200, {}, copy.deepcopy(SYSTEM)
        if (method, path) == ("GET", f"{V2}/storage"):
            return 200, {}, copy.deepcopy(STORAGE)
        if (method, path) == ("GET", f"{V2}/drives"):
            return 200, {}, copy.deepcopy(DRIVES)
        if method == "GET" and path.startswith(f"{V2}/drives/"):
            drive_id = path.rsplit("/", 1)[1]
            found = next((drive for drive in DRIVES["drives"] if drive["id"] == drive_id), None)
            if found is None:
                return 404, {}, {"err": {"msg": "not found"}}
            return 200, {}, {key: value for key, value in found.items() if key not in ("protections", "memberCount")}
        if (method, path) == ("GET", f"{V1}/services/settings"):
            return 200, {}, _envelope(copy.deepcopy(SERVICE_SETTINGS))
        for service, enabled in self.services.items():
            service_path = f"{V1}/services/{service}/settings"
            if path != service_path:
                continue
            if method == "PUT":
                self.services[service] = bool(json_body["enable"])
                if service == "smb" and not json_body["enable"]:
                    self.services["time-machine"] = False
                return 200, {}, _envelope({})
            if method == "GET":
                return 200, {}, _envelope({"enable": enabled})
        if (method, path) == ("GET", NFS_SETTINGS):
            return 200, {}, _envelope({"connections": copy.deepcopy(self.connections)})
        if (method, path) == ("PATCH", NFS_SETTINGS):
            self.connections = [
                {**entry, "errorCodes": [], "sharedDrives": self._grant_names(entry.get("sharedDrives", []))}
                for entry in json_body["connections"]
            ]
            return 200, {}, _envelope({})
        if (method, path) == ("POST", HOSTNAME_CHECK):
            return 200, {}, _envelope({"hostnames": [{"hostname": name} for name in json_body["hostnames"]]})
        if method == "GET":
            found = self._read(path)
            if found is not None:
                return found
        return 599, {}, {"err": {"msg": "unscripted"}}

    def _read(self, path: str) -> tuple[int, dict[str, str], Any] | None:
        """The read-only endpoints; ``path`` may carry a query string."""
        route, _, query = path.partition("?")
        if route == f"{V2}/systems/log-definitions":
            return 200, {}, copy.deepcopy(LOG_DEFINITIONS)
        if route == f"{V2}/systems/logs":
            # The first page names a next page; the page after it is the last.
            if "nextToken=" in query:
                return 200, {}, {"logs": copy.deepcopy(LOGS["logs"][1:])}
            return 200, {}, {**copy.deepcopy(LOGS), "nextToken": LOG_CURSOR}
        reads = {
            f"{V2}/storage/usage": STORAGE_USAGE,
            f"{V2}/systems/network-io": NETWORK_IO,
            f"{V2}/systems/fan-control": FAN_CONTROL,
            f"{V2}/systems/disk-stats": DISK_STATS,
            f"{V2}/services/rsync/settings": RSYNC,
            f"{V2}/groups": GROUPS,
        }
        if route in reads:
            return 200, {}, copy.deepcopy(reads[route])
        enveloped = {
            f"{V1}/services/smb/advanced-settings": SMB_ADVANCED,
            f"{V1}/systems/info": SYSTEMS_INFO,
            f"{V1}/systems/snapshot": SNAPSHOT_OVERVIEW,
            f"{V1}/users": USERS,
        }
        if route in enveloped:
            return 200, {}, _envelope(copy.deepcopy(enveloped[route]))
        if route.startswith(f"{V1}/snapshots/shared/"):
            name = route.rsplit("/", 1)[1]
            if name not in SNAPSHOTS:
                # Drive answers 403, not 404, for a name no shared drive has.
                return 403, {}, {"err": {"msg": "Forbidden"}, "type": "single", "data": []}
            return 200, {}, _envelope(copy.deepcopy(SNAPSHOTS[name]))
        return None


def transport_failure(method: str, path: str) -> UniFiConnectionError:
    """The error the real transport raises when a request gets no answer."""
    return UniFiConnectionError(
        f"UniFi Drive request {method} {path} timed out. Check that the configured host is reachable."
    )


def drive_cm(nas: FakeDrive) -> DriveConnectionManager:
    cm = DriveConnectionManager(NAS_HOST, "synthetic-user", "synthetic-password", base_url=f"https://{NAS_HOST}")
    cm._send = nas.send  # the transport only; everything above it is real
    return cm


async def bootstrap(tmp_path, *, products: str = "drive", scopes: str = "admin", redact: bool = True):
    """An app with one default controller declaring ``products`` and a key with ``scopes``."""
    return await _bootstrap(tmp_path, products=products, scopes=scopes, redact=redact)


def install(app, cid: str, cm) -> None:
    app.state.manager_factory._connection_cache[(cid, "drive", None)] = cm
