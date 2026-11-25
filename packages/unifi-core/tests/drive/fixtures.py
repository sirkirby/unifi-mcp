"""Sanitized UniFi Drive responses captured from a UNAS Pro 8 (UniFi OS 5.0.12).

Shapes are as captured; ids, serials, MACs and addresses are replaced with
synthetic values (TEST-NET addresses, documentation MACs).
"""

from __future__ import annotations

import copy
from typing import Any

POOL_ID = "11111111-1111-4111-8111-111111111111"
RAID_GROUP_ID = "aaaaaaaa:bbbbbbbb:cccccccc:dddddddd"
DRIVE_ID = "22222222-2222-4222-8222-222222222222"
OTHER_DRIVE_ID = "33333333-3333-4333-8333-333333333333"
CLIENT = "192.0.2.76"
OTHER_CLIENT = "192.0.2.77"


def _empty_slot(slot: str) -> dict[str, Any]:
    return {
        "slotId": slot,
        "poolId": "",
        "raidGroupId": "",
        "isGlobalHotSpare": False,
        "isLocalHotSpare": False,
        "type": "",
        "state": "empty",
        "rpm": 0,
        "model": "",
        "size": 0,
        "sata": "",
        "ata": "",
        "nvmeVersion": "",
        "firmware": "",
        "sectorFormat": "",
        "serial": "",
        "temperature": 0,
        "powerOnHours": 0,
        "badSectorCount": 0,
        "uncorrectableSectorCount": 0,
        "readErrorRate": 0,
        "smartReadErrorCount": 0,
        "riskReasons": [],
        "incompatibleReasons": [],
    }


_STORAGE = {
    "pools": [
        {
            "number": 1,
            "id": POOL_ID,
            "preferLevel": "raid5",
            "type": "lvm",
            "status": "noDataProtectionYet",
            "capacity": 15992168120320,
            "usage": 146655412224,
            "activeRaidGroupId": RAID_GROUP_ID,
            "raidGroups": [
                {
                    "number": 1,
                    "id": RAID_GROUP_ID,
                    "remnantReason": "",
                    "isSSDCache": False,
                    "currentLevel": "raid1",
                    "configLevel": "raid5",
                    "currentProtection": 0,
                    "expectedProtection": 1,
                    "recommendedDiskSize": 16000900661248,
                    "progress": 0,
                    "estimate": 0,
                }
            ],
            "initializingStatus": "successful",
        }
    ],
    "disks": [
        {
            **_empty_slot("1"),
            "poolId": POOL_ID,
            "raidGroupId": RAID_GROUP_ID,
            "type": "HDD",
            "state": "optimal",
            "rpm": 7200,
            "model": "WDC WD160EDGZ-11B2DA0",
            "size": 16000900661248,
            "sata": "SATA 3.3",
            "ata": "ACS-4",
            "firmware": "85.00A85",
            "sectorFormat": "512E",
            "serial": "FAKESERIAL1",
            "temperature": 33,
            "powerOnHours": 15592,
        },
        *(_empty_slot(str(slot)) for slot in range(2, 9)),
    ],
    "cacheSlots": [_empty_slot("1"), _empty_slot("2")],
}

_DRIVES = {
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
    ]
}

_SINGLE_DRIVE = {
    "id": DRIVE_ID,
    "type": "shared",
    "name": "Shared_Drive",
    "status": "active",
    "storagePoolId": POOL_ID,
    "quota": -1,
    "usage": 146210029568,
    "role": "admin",
}

_SERVICES_SETTINGS = {
    "err": None,
    "type": "single",
    "data": {
        "customDomain": "",
        "networkInterfaces": [
            {
                "interface": "ethernet",
                "interfaceName": "enp0s0",
                "connected": True,
                "maxSpeed": "10 GbE",
                "linkSpeed": "10 GbE",
                "address": "192.0.2.10",
                "mac": "00:00:5e:00:53:01",
            },
            {"interface": "sfp+", "interfaceName": "enp0s1", "connected": False, "maxSpeed": "10 GbE", "linkSpeed": ""},
        ],
    },
}

_NFS_ADVANCED = {
    "err": None,
    "type": "single",
    "data": {
        "connections": [
            {
                "client": CLIENT,
                "async": False,
                "errorCodes": [],
                "sharedDrives": [
                    {
                        "id": DRIVE_ID,
                        "name": "Shared_Drive",
                        "status": "active",
                        "encryptionStatus": "unencrypted",
                        "permission": "rw",
                    }
                ],
            }
        ]
    },
}

_SYSTEM = {
    "name": "UNAS Pro 8",
    "hostname": "UNAS-Pro-8",
    "mac": "00005E005302",
    "isSetup": True,
    "timezone": "America/New_York",
    "deviceState": "updateAvailable",
    "uptime": 5269.06,
    "cpu": {"model": "unknown", "currentload": 0.169, "temperature": 64},
    "memory": {"free": 1363840, "total": 16639296, "available": 13053120},
    "hardware": {"name": "UniFi Network Attached Storage Pro 8", "shortname": "UNASPRO8", "firmwareVersion": "5.0.12"},
    "location": {"lat": 0.0, "long": 0.0, "text": "synthetic location"},
    "publicIp": "198.51.100.1",
    "owner": {"full_name": "admin", "unique_id": "synthetic-owner"},
    "devices": {
        "unifiOS": [
            {
                "mac": "00005E005302",
                "firmware": "5.0.12",
                "updateAvailable": "5.0.17+3f9b9ea",
                "source": "self",
            }
        ]
    },
    "apps": {
        "controllers": [
            {
                "name": "drive",
                "type": "controller",
                "version": "4.4.31",
                "versionRaw": "4.4.31",
                "updateAvailable": "4.5.7",
                "state": "active",
                "isRunning": True,
            }
        ]
    },
}


def storage() -> dict[str, Any]:
    return copy.deepcopy(_STORAGE)


def drives() -> dict[str, Any]:
    return copy.deepcopy(_DRIVES)


def single_drive() -> dict[str, Any]:
    return copy.deepcopy(_SINGLE_DRIVE)


def services_settings() -> dict[str, Any]:
    return copy.deepcopy(_SERVICES_SETTINGS)


def nfs_advanced(*connections: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(_NFS_ADVANCED)
    if connections:
        body["data"]["connections"] = [copy.deepcopy(c) for c in connections]
    return body


def nfs_connection(client: str, *grants: tuple[str, str, str], async_writes: bool = False) -> dict[str, Any]:
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


def service(enabled: bool) -> dict[str, Any]:
    return {"err": None, "type": "single", "data": {"enable": enabled}}


def system() -> dict[str, Any]:
    return copy.deepcopy(_SYSTEM)


# System log, captured from UniFi OS 6.0.18 / Drive 4.4.31 and trimmed to a few
# entries and definitions. Names, addresses and ids are synthetic.
_LOGS = {
    "logs": [
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "category": "activity",
            "type": "userAccess",
            "name": "UniFiDriveAccessedDirectV1",
            "severity": "low",
            "data": {"address": "192.0.2.5", "platform": "Other OS", "user": "synthetic-user"},
            "panels": {
                "targetUser": {"data": {"type": "user", "data": {"id": "55555555-5555-4555-8555-555555555555"}}}
            },
            "createdAt": "2026-11-25T08:35:06.741745-05:00",
        },
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

_LOG_DEFINITIONS = {
    "categories": {"activity": "Activity", "settings": "Settings", "storage": "Storage"},
    "types": {
        "drive": "Drive",
        "fanMode": "Fan Mode",
        "storagePool": "Storage Pool",
        "userAccess": "User Access",
    },
    "categoryTypes": {
        "activity": ["userAccess"],
        "settings": ["fanMode"],
        "storage": ["storagePool", "drive"],
    },
    "panelLabels": {"accessedFrom": "Accessed From"},
    "generalEventNames": [{"name": "UniFiDriveAccessed", "title": "UniFi Drive Accessed"}],
    "events": {
        "UniFiDriveAccessedDirectV1": {
            "title": "UniFi Drive Accessed",
            "description": "{user} accessed UniFi Drive from {address}({platform}).",
            "panels": [{"name": "targetUser", "description": "{user}"}],
        },
        "StoragePoolArrayAtRiskSingleV1": {
            "title": "Storage Pool Array at Risk",
            "description": "{storagePool} is degraded. {drive} is showing pre-failure indicators.",
            "panels": [],
        },
        "DriveInsertedV1": {
            "title": "Drive Inserted",
            "description": "{drive} was inserted and is ready to use.",
            "panels": [],
        },
    },
}


def logs(*, next_token: str | None = None) -> dict[str, Any]:
    body = copy.deepcopy(_LOGS)
    if next_token:
        body["nextToken"] = next_token
    return body


def log_definitions() -> dict[str, Any]:
    return copy.deepcopy(_LOG_DEFINITIONS)
