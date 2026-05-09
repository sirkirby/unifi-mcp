"""Shared bootstrap utilities for MCP servers.

Provides common config loading logic and registration mode validation
that all servers (network, protect, access) share.
"""

from __future__ import annotations

import importlib.resources
import logging
import os
from pathlib import Path
from typing import Any, Sequence


def load_server_config(
    *,
    package_name: str,
    env_prefix: str,
    keys: Sequence[str] = ("host", "username", "password", "port", "site", "verify_ssl", "api_key"),
    logger: logging.Logger,
):
    """Load YAML config with environment variable substitution.

    Order of precedence:
    1. Environment variable ``CONFIG_PATH``
    2. Relative path ``config/config.yaml`` in current working directory
    3. Default ``config.yaml`` bundled within the package

    Then merges server-specific env vars (e.g. ``UNIFI_NETWORK_HOST``)
    with fallback to shared vars (e.g. ``UNIFI_HOST``).

    Args:
        package_name: Dotted package name for importlib.resources
                      (e.g. ``"unifi_network_mcp.config"``).
        env_prefix: Server-specific prefix without ``UNIFI_`` and trailing ``_``
                    (e.g. ``"NETWORK"``, ``"PROTECT"``, ``"ACCESS"``).
        keys: Tuple of config keys to merge from env vars.
        logger: Logger instance for status messages.

    Returns:
        An OmegaConf config object.
    """
    from omegaconf import OmegaConf

    config_path_str: str | None = os.getenv("CONFIG_PATH")
    resolved_path: Path | None = None

    if config_path_str:
        path = Path(config_path_str).expanduser()
        if path.exists() and path.is_file():
            resolved_path = path
            logger.info("Using configuration file from CONFIG_PATH: %s", path)
        else:
            logger.error("Configuration file specified by CONFIG_PATH not found: %s", path)
            raise SystemExit(2)
    else:
        relative_path = Path("config/config.yaml")
        if relative_path.exists() and relative_path.is_file():
            resolved_path = relative_path
            logger.info("Using configuration file from relative path: %s", relative_path)
        else:
            try:
                config_file_ref = importlib.resources.files(package_name).joinpath("config.yaml")
                if config_file_ref.is_file():
                    resolved_path = Path(str(config_file_ref))
                    logger.info("Using bundled default configuration: %s", resolved_path)
                else:
                    logger.error("Bundled default configuration file could not be accessed (not a file).")
                    raise SystemExit(3)
            except Exception as e:
                logger.error("Could not find or access bundled default configuration: %s", e)
                raise SystemExit(3)

    if resolved_path is None:
        logger.critical("Failed to determine configuration file path.")
        raise SystemExit(4)

    cfg = OmegaConf.load(str(resolved_path))

    # Merge env vars: server-specific (e.g. UNIFI_NETWORK_HOST) > shared (UNIFI_HOST)
    unifi_env_overrides: dict[str, Any] = {}
    for key in keys:
        server_key = f"UNIFI_{env_prefix}_{key.upper()}"
        shared_key = f"UNIFI_{key.upper()}"
        val = os.getenv(server_key) or os.getenv(shared_key)
        if val is not None:
            if key == "verify_ssl":
                val = val.lower() in {"1", "true", "yes"}
            elif key == "controller_type":
                val = val.lower()
            unifi_env_overrides[key] = val

    if unifi_env_overrides:
        logger.debug("Applying env overrides to %s config: %s", env_prefix, unifi_env_overrides)
        cfg.unifi = OmegaConf.merge(cfg.unifi, unifi_env_overrides)

    return cfg


# ---------------------------------------------------------------------------
# Registration mode validation
# ---------------------------------------------------------------------------

VALID_REGISTRATION_MODES = {"lazy", "eager", "meta_only"}


def assert_credentials_configured(
    cfg: Any,
    *,
    plugin_name: str,
    env_prefix: str,
    logger: logging.Logger,
) -> None:
    """Refuse to start if no controller host has been configured.

    Empty host is the universal "user hasn't run setup yet" signal — without it
    every tool call will fail with an unhelpful connection error. Surfacing the
    problem at startup makes the server appear as failed in ``/mcp`` instead of
    "connected but every tool errors", which is the most common new-user
    confusion mode.

    Args:
        cfg: Loaded OmegaConf config (must have a ``unifi`` section).
        plugin_name: Human-facing plugin name (e.g. ``"unifi-network"``).
        env_prefix: Server-specific env prefix without ``UNIFI_`` and trailing
                    ``_`` (e.g. ``"NETWORK"``).
        logger: Logger to write the error to.

    Raises:
        SystemExit: with code 5 when host is unconfigured. The MCP harness will
                    show the server as failed, which is the desired UX.
    """
    host = ""
    try:
        host = str(cfg.unifi.get("host", "") or "").strip()
    except Exception:
        pass

    if host:
        return

    var_prefix = f"UNIFI_{env_prefix}_"
    bar = "=" * 72
    logger.error(bar)
    logger.error("[%s] No controller host configured — refusing to start.", plugin_name)
    logger.error("")
    logger.error("Set these environment variables before starting the server:")
    logger.error("  %sHOST=<your-controller-ip-or-hostname>", var_prefix)
    logger.error("  %sUSERNAME=<local-admin-username>", var_prefix)
    logger.error("  %sPASSWORD=<local-admin-password>", var_prefix)
    logger.error("")
    logger.error("How to set them depends on your runtime:")
    logger.error("  Claude Code plugin -> run the /setup skill")
    logger.error("  Docker             -> docker-compose .env or `environment:`")
    logger.error("  Direct uvx / shell -> export them before launching")
    logger.error("")
    logger.error("Then restart the server.")
    logger.error(bar)
    raise SystemExit(5)


def validate_registration_mode(logger: logging.Logger) -> str:
    """Read and validate UNIFI_TOOL_REGISTRATION_MODE from environment.

    Returns:
        A validated registration mode string ("lazy", "eager", or "meta_only").
    """
    mode = os.getenv("UNIFI_TOOL_REGISTRATION_MODE", "lazy").lower()
    if mode not in VALID_REGISTRATION_MODES:
        logger.warning(
            "Invalid UNIFI_TOOL_REGISTRATION_MODE: '%s'. Must be one of: %s. Defaulting to 'lazy'.",
            mode,
            ", ".join(sorted(VALID_REGISTRATION_MODES)),
        )
        mode = "lazy"
    return mode
