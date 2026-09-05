# ruff: noqa: E402
from __future__ import annotations

"""Bootstrap utilities for the UniFi-Access MCP server.

This module consolidates:
- environment loading
- logging configuration
- configuration loading / validation

Importing it early guarantees deterministic side-effects (env + logging) and
exposes a `load_config()` helper that the rest of the codebase can share.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from omegaconf import OmegaConf

from unifi_core.config import load_yaml_config  # noqa: F401 -- re-export for convenience
from unifi_core.config import setup_logging as _shared_setup_logging

# ---------------------------------------------------------------------------
# Environment & logging
# ---------------------------------------------------------------------------
# Record which variables the process was started with before any .env is read:
# the UNIFI_*_FILE / _COMMAND credential indirections are honoured only from there,
# so a .env in an untrusted project directory cannot make the server run a program.
from unifi_mcp_shared.bootstrap import snapshot_process_env

snapshot_process_env()

load_dotenv()
# Under an installed package (pip/uvx), find_dotenv() walks up from this file's
# site-packages location and never reaches the caller's project, so also load a
# .env from the process working directory (MCP clients spawn servers with the
# project as cwd). Real environment variables still take precedence.
load_dotenv(Path.cwd() / ".env", override=False)


DEFAULT_LOG_LEVEL = os.getenv("UNIFI_MCP_LOG_LEVEL", "INFO").upper()


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure root logger once and return the project logger."""
    return _shared_setup_logging("unifi-access-mcp", level=level or DEFAULT_LOG_LEVEL)


logger = setup_logging()


# ---------------------------------------------------------------------------
# Domain config dataclasses  -------------------------------------------------
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AccessSettings:
    host: str
    username: str
    password: str
    port: int = 443
    site: str = "default"
    verify_ssl: bool = False
    api_key: str = ""  # Optional API key for official API access

    @classmethod
    def from_omegaconf(cls, cfg: Any) -> "AccessSettings":
        """Create from an OmegaConf config object."""
        return cls(
            host=str(cfg.host),
            username=str(cfg.username),
            password=str(cfg.password),
            port=int(cfg.get("port", 443)),
            site=str(cfg.get("site", "default")),
            verify_ssl=bool(cfg.get("verify_ssl", False)),
            api_key=str(cfg.get("api_key", "")),
        )


# ---------------------------------------------------------------------------
# Config loading  -----------------------------------------------------------
# ---------------------------------------------------------------------------


def load_config(path_override: str | Path | None = None) -> OmegaConf:
    """Load YAML config with environment variable substitution."""
    from unifi_mcp_shared.bootstrap import load_server_config

    return load_server_config(
        package_name="unifi_access_mcp.config",
        env_prefix="ACCESS",
        keys=("host", "username", "password", "port", "site", "verify_ssl", "api_key"),
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Tool registration mode
# ---------------------------------------------------------------------------

from unifi_mcp_shared.bootstrap import validate_registration_mode

UNIFI_TOOL_REGISTRATION_MODE = validate_registration_mode(logger)
