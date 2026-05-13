# ruff: noqa: E402
from __future__ import annotations

"""Bootstrap utilities for the UniFi‑Network MCP server.

This module consolidates:
• environment loading
• logging configuration
• configuration loading / validation

Importing it early guarantees deterministic side‑effects (env + logging) and
exposes a `load_config()` helper that the rest of the codebase can share.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from unifi_core.config import load_yaml_config  # noqa: F401 — re-export for convenience
from unifi_core.config import setup_logging as _shared_setup_logging

# ---------------------------------------------------------------------------
# Environment & logging
# ---------------------------------------------------------------------------

load_dotenv()


DEFAULT_LOG_LEVEL = os.getenv("UNIFI_MCP_LOG_LEVEL", "INFO").upper()


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure root logger once and return the project logger."""
    return _shared_setup_logging("unifi-network-mcp", level=level or DEFAULT_LOG_LEVEL)


logger = setup_logging()


# ---------------------------------------------------------------------------
# Domain config dataclasses  -------------------------------------------------
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UniFiSettings:
    host: str
    username: str
    password: str
    port: int = 443
    site: str = "default"
    verify_ssl: bool = False
    controller_type: str = "auto"
    api_key: str = ""  # Optional API key for official API access

    @classmethod
    def from_omegaconf(cls, cfg: Any) -> "UniFiSettings":
        """Create from an OmegaConf config object."""
        return cls(
            host=str(cfg.host),
            username=str(cfg.username),
            password=str(cfg.password),
            port=int(cfg.get("port", 443)),
            site=str(cfg.get("site", "default")),
            verify_ssl=bool(cfg.get("verify_ssl", False)),
            controller_type=str(cfg.get("controller_type", "auto")),
            api_key=str(cfg.get("api_key", "")),
        )


# ---------------------------------------------------------------------------
# Config loading  -----------------------------------------------------------
# ---------------------------------------------------------------------------


def load_config(path_override: str | Path | None = None):
    """Load YAML config with environment variable substitution."""
    from unifi_mcp_shared.bootstrap import load_server_config

    return load_server_config(
        package_name="unifi_network_mcp.config",
        env_prefix="NETWORK",
        keys=("host", "username", "password", "port", "site", "verify_ssl", "controller_type", "api_key"),
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Controller Type Configuration
# ---------------------------------------------------------------------------

# Controller type determines API path structure. The resolution + validation
# logic lives in unifi-core so every consumer (network MCP, unifi-api-server,
# future SDKs) shares one source of truth — see commit history for the bug
# that motivated extracting it.
from unifi_core.network.controller_type import (  # noqa: E402
    resolve_controller_type,
)

UNIFI_CONTROLLER_TYPE = resolve_controller_type()

from unifi_mcp_shared.bootstrap import validate_registration_mode

UNIFI_TOOL_REGISTRATION_MODE = validate_registration_mode(logger)
