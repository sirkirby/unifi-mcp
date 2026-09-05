"""Shared bootstrap utilities for MCP servers.

Provides common config loading logic and registration mode validation
that all servers (network, protect, access) share.
"""

from __future__ import annotations

import importlib.resources
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, NoReturn, Sequence

# Config keys whose values are credentials. Each accepts three env spellings
# (``UNIFI_<PREFIX>_<KEY>``, ``..._FILE``, ``..._COMMAND``) and is masked in logs.
SECRET_KEYS: frozenset[str] = frozenset({"password", "api_key"})

# Exit code used when a credential indirection cannot be resolved.
EXIT_SECRET_UNRESOLVED = 6

_SECRET_COMMAND_TIMEOUT_S = 30
_SECRET_STDERR_TAIL = 512
_SECRET_MAX_BYTES = 64 * 1024

# The environment the process was started with, recorded by snapshot_process_env()
# before any .env file is loaded. ``None`` means no snapshot was taken and the
# current environment is trusted as is.
_TRUSTED_ENV: dict[str, str] | None = None


def snapshot_process_env() -> None:
    """Record the real process environment before any ``.env`` file is loaded.

    Call this before ``load_dotenv()``. Afterwards :func:`resolve_env` honours the
    ``_FILE`` and ``_COMMAND`` spellings only for variables present in this snapshot,
    and runs the command in this environment rather than the merged one, so a
    ``.env`` in the working directory (which MCP clients set to the user's project)
    can still supply a value but can never make the server read an arbitrary file,
    run a program, or inject loader variables such as ``PYTHONPATH`` into the helper.
    The first call wins; later calls do not widen the snapshot.
    """
    global _TRUSTED_ENV
    if _TRUSTED_ENV is None:
        _TRUSTED_ENV = dict(os.environ)


_INTERPOLATION_START = re.compile(r"(\\*)(\$\{)")


def _escape_interpolation(value: str) -> str:
    """Keep ``${`` literal when the value lands in an OmegaConf node.

    OmegaConf reads ``\\${`` as a literal ``${`` and collapses only the backslash run
    immediately before it, so that run is doubled and one more backslash is added.
    Backslashes elsewhere are already literal and must stay single.
    """
    if "${" not in value:
        return value
    return _INTERPOLATION_START.sub(lambda m: "\\" * (2 * len(m.group(1))) + "\\${", value)


def _fail_secret(logger: logging.Logger, message: str, *args: Any) -> NoReturn:
    logger.error("[credentials] " + message, *args)
    logger.error("[credentials] Refusing to start until the credential source is fixed.")
    raise SystemExit(EXIT_SECRET_UNRESOLVED)


def _read_secret_file(var: str, path_str: str, logger: logging.Logger) -> str:
    path = Path(path_str)
    try:
        path = path.expanduser()
    except RuntimeError:
        _fail_secret(
            logger, "%s starts with ~ but the home directory could not be determined; use an absolute path.", var
        )
    try:
        if not path.exists():
            _fail_secret(logger, "%s points at %s, which does not exist (cwd: %s).", var, path, Path.cwd())
        if not path.is_file():
            _fail_secret(logger, "%s points at %s, which is not a regular file.", var, path)
        if os.name != "nt" and path.stat().st_mode & 0o077:
            logger.warning(
                "[credentials] %s points at %s with mode %04o; consider chmod 600 so other users cannot read it.",
                var,
                path,
                path.stat().st_mode & 0o777,
            )
        with path.open("rb") as handle:
            data = handle.read(_SECRET_MAX_BYTES + 1)
    except OSError as exc:
        _fail_secret(logger, "%s points at %s, which could not be read: %s", var, path, exc.strerror or exc)
    if len(data) > _SECRET_MAX_BYTES:
        _fail_secret(logger, "%s points at %s, which is larger than %d bytes.", var, path, _SECRET_MAX_BYTES)
    try:
        # utf-8-sig drops a BOM left by editors that save "UTF-8 with BOM".
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail_secret(logger, "%s points at %s, which is not valid UTF-8.", var, path)


def _run_secret_command(var: str, command: str, logger: logging.Logger) -> str:
    """Run *command* as an argv (no shell) and return its stdout."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        _fail_secret(logger, "%s could not be parsed as a command: %s", var, exc)
    if not argv:
        _fail_secret(logger, "%s is set but contains no command.", var)
    try:
        # argv comes from the operator's own environment; no shell is involved.
        # stdin is closed: under stdio transport it is the MCP client's pipe, and a
        # prompting helper (gpg, op, sudo) must not read from it.
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            timeout=_SECRET_COMMAND_TIMEOUT_S,
            check=False,
            env=_TRUSTED_ENV,  # the starting environment, never the .env-merged one
        )
    except OSError as exc:
        # FileNotFoundError, PermissionError (a data file given as the command), etc.
        _fail_secret(logger, "%s: could not run %r: %s", var, argv[0], exc.strerror or exc)
    except subprocess.TimeoutExpired:
        _fail_secret(
            logger,
            "%s: %r did not finish within %ss (or left a background process holding its output open).",
            var,
            argv[0],
            _SECRET_COMMAND_TIMEOUT_S,
        )
    except UnicodeDecodeError:
        _fail_secret(logger, "%s: %r printed output that is not valid UTF-8.", var, argv[0])
    if proc.returncode != 0:
        # stdout may hold the secret even on failure; only stderr is surfaced, and only
        # its tail, since debug tracing can put tokens or megabytes there.
        stderr = proc.stderr.strip()
        if len(stderr) > _SECRET_STDERR_TAIL:
            stderr = "(truncated) ..." + stderr[-_SECRET_STDERR_TAIL:]
        _fail_secret(
            logger, "%s: %r exited with exit status %s. stderr: %s", var, argv[0], proc.returncode, stderr or "(empty)"
        )
    if len(proc.stdout) > _SECRET_MAX_BYTES:
        _fail_secret(logger, "%s: %r printed more than %d bytes.", var, argv[0], _SECRET_MAX_BYTES)
    return proc.stdout


def resolve_env(key: str, *, env_prefix: str, logger: logging.Logger) -> str | None:
    """Resolve one config key from the environment.

    Checks the server-specific level (``UNIFI_<PREFIX>_<KEY>``) and then the shared
    level (``UNIFI_<KEY>``). An empty variable counts as unset, so a plugin
    ``.mcp.json`` that interpolates ``"${UNIFI_NETWORK_PASSWORD:-}"`` does not shadow
    the shared level.

    Keys in :data:`SECRET_KEYS` accept three spellings at each level:

    * ``<VAR>``          the value itself
    * ``<VAR>_FILE``     a path whose contents are the value (trailing newlines dropped)
    * ``<VAR>_COMMAND``  an argv, run without a shell, whose stdout is the value

    Setting two spellings at one level, or an indirection that cannot be read,
    refuses startup with :data:`EXIT_SECRET_UNRESOLVED`.

    Returns:
        The resolved value, or ``None`` when nothing is set at either level.
    """
    upper = key.upper()
    suffixes = ("", "_FILE", "_COMMAND") if key in SECRET_KEYS else ("",)
    for base in (f"UNIFI_{env_prefix}_{upper}", f"UNIFI_{upper}"):
        present = {suffix: value for suffix in suffixes if (value := os.getenv(f"{base}{suffix}"))}
        if not present:
            continue
        if len(present) > 1:
            names = ", ".join(
                f"{base}{suffix}"
                + ("" if _TRUSTED_ENV is None or f"{base}{suffix}" in _TRUSTED_ENV else " (from a .env file)")
                for suffix in present
            )
            _fail_secret(logger, "%s are all set; keep exactly one of them.", names)
        ((suffix, value),) = present.items()
        var = f"{base}{suffix}"
        if not suffix:
            return value
        if _TRUSTED_ENV is not None and var not in _TRUSTED_ENV:
            _fail_secret(
                logger,
                "%s was supplied by a .env file, not by the environment the server was started with; "
                "credential indirection is only honoured from the process environment.",
                var,
            )
        if suffix == "_FILE":
            value = _read_secret_file(var, value, logger)
        else:
            value = _run_secret_command(var, value, logger)
        value = value.rstrip("\r\n")
        if not value:
            _fail_secret(logger, "%s resolved to an empty value.", var)
        if "\n" in value:
            # A second line is a warning or prompt, not part of the secret; a wrong
            # value accepted here would surface later as an unexplained 401.
            _fail_secret(logger, "%s produced %d lines; expected exactly one.", var, value.count("\n") + 1)
        return value
    return None


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
    with fallback to shared vars (e.g. ``UNIFI_HOST``) via :func:`resolve_env`.
    Keys in :data:`SECRET_KEYS` may also be supplied as ``..._FILE`` or
    ``..._COMMAND``.

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
        val = resolve_env(key, env_prefix=env_prefix, logger=logger)
        if val is not None:
            if key == "verify_ssl":
                val = val.lower() in {"1", "true", "yes"}
            elif key == "controller_type":
                val = val.lower()
            else:
                if key in SECRET_KEYS and val == "???":
                    # OmegaConf's missing-value marker; it cannot be stored literally.
                    _fail_secret(logger, "the %s value '???' cannot be represented; choose another.", key)
                # Keep "${" literal: a generated password may contain it, and a value
                # from a .env must not be able to interpolate other variables.
                val = _escape_interpolation(val)
            unifi_env_overrides[key] = val

    if unifi_env_overrides:
        from unifi_core.redaction import redact_sensitive_fields

        logger.debug(
            "Applying env overrides to %s config: %s", env_prefix, redact_sensitive_fields(unifi_env_overrides)
        )
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
