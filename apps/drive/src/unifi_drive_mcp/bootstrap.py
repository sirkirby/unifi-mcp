# ruff: noqa: E402
from __future__ import annotations

"""Bootstrap for the UniFi Drive MCP server: environment, logging, config."""

import logging
import os
from pathlib import Path

from omegaconf import OmegaConf

from unifi_core.config import setup_logging as _shared_setup_logging

# Use only the launcher-supplied environment. Project .env files are never loaded:
# they must not select credential destinations or weaken permissions/redaction.
# Operators can load a trusted env file in their launcher, or name a per-user
# settings file in UNIFI_SETTINGS_FILE.
from unifi_mcp_shared.bootstrap import load_process_env, report_settings_file

load_process_env()


DEFAULT_LOG_LEVEL = os.getenv("UNIFI_MCP_LOG_LEVEL", "INFO").upper()


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure root logger once and return the project logger."""
    return _shared_setup_logging("unifi-drive-mcp", level=level or DEFAULT_LOG_LEVEL)


logger = setup_logging()
report_settings_file(logger)


def load_config(path_override: str | Path | None = None) -> OmegaConf:
    """Load YAML config, merging ``UNIFI_DRIVE_*`` variables.

    The NAS is its own console, so its host and login come from ``UNIFI_DRIVE_*``
    only. The shared ``UNIFI_HOST``/``UNIFI_USERNAME``/``UNIFI_PASSWORD`` name the
    gateway and are never sent to the NAS. Port and ``verify_ssl`` still fall
    back to the shared level.
    """
    from unifi_mcp_shared.bootstrap import load_server_config

    return load_server_config(
        package_name="unifi_drive_mcp.config",
        env_prefix="DRIVE",
        keys=("host", "username", "password", "port", "verify_ssl"),
        logger=logger,
        isolated_keys=("host", "username", "password"),
    )


from unifi_mcp_shared.bootstrap import validate_registration_mode

UNIFI_TOOL_REGISTRATION_MODE = validate_registration_mode(logger)
