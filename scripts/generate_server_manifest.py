#!/usr/bin/env python3
"""Generate server.json manifest for MCP Registry submission.

Shared script for all 3 apps. Parameterized by app name.

Usage:
    python scripts/generate_server_manifest.py --app network [--version X.Y.Z]
    python scripts/generate_server_manifest.py --app protect [--version X.Y.Z]
    python scripts/generate_server_manifest.py --app access [--version X.Y.Z]

Output:
    apps/{app}/server.json — MCP Registry manifest (committed to git)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent if Path(__file__).parent.name == "scripts" else Path(__file__).parent

# Shared env vars (all apps need these)
_SHARED_ENV_VARS = [
    {"name": "UNIFI_HOST", "description": "Controller IP/hostname", "isRequired": True},
    {"name": "UNIFI_USERNAME", "description": "Admin username", "isRequired": True, "isSecret": True},
    {"name": "UNIFI_PASSWORD", "description": "Admin password", "isRequired": True, "isSecret": True},
    {"name": "UNIFI_API_KEY", "description": "API key (optional, experimental)", "isRequired": False, "isSecret": True},
    {"name": "UNIFI_PORT", "description": "Controller HTTPS port", "isRequired": False, "default": "443"},
    {
        "name": "UNIFI_VERIFY_SSL",
        "description": "SSL certificate verification",
        "isRequired": False,
        "default": "false",
    },
]

# Per-app configuration
APP_CONFIGS = {
    "network": {
        "title": "UniFi Network MCP",
        "description": "Manage UniFi Network devices, clients, firewall, VLANs, VPNs, and more via MCP.",
        "tag_prefixes": ["network/v", "v"],
        "extra_env_vars": [
            {"name": "UNIFI_SITE", "description": "UniFi site name", "isRequired": False, "default": "default"},
        ],
    },
    "protect": {
        "title": "UniFi Protect MCP",
        "description": "Manage UniFi Protect cameras, events, recordings, and smart detections via MCP.",
        "tag_prefixes": ["protect/v", "v"],
        "extra_env_vars": [],
    },
    "access": {
        "title": "UniFi Access MCP",
        "description": "Manage UniFi Access doors, credentials, policies, visitors, and events via MCP.",
        "tag_prefixes": ["access/v", "v"],
        "extra_env_vars": [],
    },
}


def get_version_from_git(app_name: str) -> str:
    """Extract version from git tags using the app's tag prefix pattern.

    Uses ``git describe --match`` with each tag prefix to find the nearest
    matching tag, rather than the nearest tag overall.
    """
    config = APP_CONFIGS[app_name]

    for prefix in config["tag_prefixes"]:
        glob_pattern = f"{prefix}*"
        try:
            raw = subprocess.check_output(
                ["git", "describe", "--tags", "--match", glob_pattern, "--always"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            # Extract version number from tag (e.g., "network/v0.7.7-3-gabcdef" -> "0.7.7")
            version_pattern = rf"^{re.escape(prefix)}(\d+(?:\.\d+)*)"
            match = re.match(version_pattern, raw)
            if match:
                return match.group(1)
        except subprocess.CalledProcessError:
            continue

    logger.warning("No matching git tag found for app '%s'. Using 0.0.0", app_name)
    return "0.0.0"


def build_server_manifest(app_name: str, version: str) -> dict:
    """Build the server.json manifest dictionary for a given app."""
    if app_name not in APP_CONFIGS:
        raise ValueError(f"Unknown app: '{app_name}'. Expected one of: {sorted(APP_CONFIGS.keys())}")

    config = APP_CONFIGS[app_name]
    env_vars = _SHARED_ENV_VARS + config["extra_env_vars"]

    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": f"io.github.sirkirby/unifi-{app_name}-mcp",
        "title": config["title"],
        "description": config["description"],
        "version": version,
        "repository": {
            "url": "https://github.com/sirkirby/unifi-mcp",
            "source": "github",
            "subfolder": f"apps/{app_name}",
        },
        "packages": [
            {
                "registryType": "pypi",
                "identifier": f"unifi-{app_name}-mcp",
                "version": version,
                "transport": {"type": "stdio"},
                "environmentVariables": env_vars,
            }
        ],
    }


def write_server_manifest(app_name: str, version: str, output_path: Path | None = None) -> Path:
    """Generate and write server.json for a given app."""
    if output_path is None:
        output_path = REPO_ROOT / "apps" / app_name / "server.json"

    manifest = build_server_manifest(app_name, version)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    logger.info("Wrote %s (version %s)", output_path, version)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate server.json for MCP Registry")
    parser.add_argument("--app", required=True, choices=sorted(APP_CONFIGS.keys()), help="App to generate for")
    parser.add_argument("--version", help="Version string (default: from git tags)")
    args = parser.parse_args()

    version = args.version or get_version_from_git(args.app)
    write_server_manifest(args.app, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
