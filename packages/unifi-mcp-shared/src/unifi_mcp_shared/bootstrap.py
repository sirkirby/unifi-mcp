"""Shared bootstrap utilities for MCP servers.

Provides common config loading logic and registration mode validation
that all servers (network, protect, access) share.
"""

from __future__ import annotations

import contextlib
import importlib.resources
import logging
import os
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, Sequence

from unifi_core.redaction import is_sensitive_key, redact_sensitive_fields

from unifi_mcp_shared.settings_file import SETTINGS_FILE_VAR, SettingsFileReport, apply_settings_file

# Exit code used when a credential indirection cannot be resolved.
EXIT_SECRET_UNRESOLVED = 6

_SECRET_MAX_BYTES = 64 * 1024

# How long a credential helper may take, and how long its process tree gets to
# die after SIGTERM before SIGKILL.
_SECRET_COMMAND_TIMEOUT_S = 30
_SECRET_COMMAND_GRACE_S = 2
# SIGKILL delivery is asynchronous: a zero wait always races the kernel's
# teardown and loses, leaving a zombie and returncode None.
_SECRET_COMMAND_REAP_S = 0.2

# Names of the variables the process was started with, recorded by
# load_process_env() at startup. ``None`` means no snapshot
# was taken and the current environment is trusted as is.
_TRUSTED_VARS: frozenset[str] | None = None

# What load_process_env() did with UNIFI_SETTINGS_FILE; ``None`` until it runs.
_SETTINGS_REPORT: SettingsFileReport | None = None


def snapshot_process_env() -> None:
    """Record the names of the variables the process was started with.

    Call this at startup (:func:`load_process_env` does). Afterwards
    :func:`resolve_env` honours the indirect spellings (``_FILE``, ``_COMMAND``)
    only for variables present in this snapshot. The server never discovers or
    loads project ``.env`` files, so this is a second line rather than the first.
    The first call wins; later calls do not widen the snapshot.
    """
    global _TRUSTED_VARS
    if _TRUSTED_VARS is None:
        _TRUSTED_VARS = frozenset(os.environ)


def load_process_env() -> None:
    """Record the launcher-supplied environment without discovering config files.

    MCP clients may spawn the server in an untrusted project directory. Loading
    its ``.env`` would let that project choose credential destinations, policy,
    and even values read later through YAML interpolation. Operators who use an
    env file must explicitly load a trusted file in their launcher (for example,
    Docker ``env_file`` or ``uv run --env-file /absolute/trusted.env``).

    The one file read here is the per-user settings file the launcher names in
    ``UNIFI_SETTINGS_FILE`` (see :mod:`unifi_mcp_shared.settings_file`). It is
    applied before the snapshot, so its keys count as launcher-supplied: its
    ``_FILE``/``_COMMAND`` spellings are honoured and a credential helper
    inherits them, exactly as for an exported variable. Only ``UNIFI_`` keys are
    accepted, so it cannot introduce loader variables such as ``PYTHONPATH``.
    The first call loads the file; later calls do nothing.
    """
    global _SETTINGS_REPORT
    if _SETTINGS_REPORT is None:
        _SETTINGS_REPORT = apply_settings_file()
    snapshot_process_env()


def report_settings_file(logger: logging.Logger) -> None:
    """Log what :func:`load_process_env` did with the settings file, once.

    The file is loaded before logging is configured (it may set the log level),
    so its messages wait for the server's logger.
    """
    if _SETTINGS_REPORT is None:
        return
    for level, message, args in _SETTINGS_REPORT.messages:
        logger.log(level, message, *args)
    _SETTINGS_REPORT.messages.clear()


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


def _origin(var: str) -> str:
    """The variable name, tagged when a .env supplied it rather than the process environment."""
    if _TRUSTED_VARS is None or var in _TRUSTED_VARS:
        return var
    return f"{var} (from a .env file)"


def _read_secret_file(var: str, path_str: str, logger: logging.Logger) -> str:
    path = Path(path_str)
    try:
        path = path.expanduser()
    except RuntimeError:
        _fail_secret(
            logger, "%s starts with ~ but the home directory could not be determined; use an absolute path.", var
        )
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        _fail_secret(logger, "%s points at %s, which does not exist (cwd: %s).", var, path, Path.cwd())
    except OSError as exc:
        _fail_secret(logger, "%s points at %s, which could not be read: %s", var, path, exc.strerror or exc)
    if not stat.S_ISREG(mode):
        _fail_secret(logger, "%s points at %s, which is not a regular file.", var, path)
    if os.name != "nt" and mode & 0o077:
        logger.warning(
            "[credentials] %s points at %s with mode %04o; consider chmod 600 so other users cannot read it.",
            var,
            path,
            mode & 0o777,
        )
    try:
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


def _trusted_environ() -> dict[str, str]:
    """The environment restricted to the names the process was started with.

    The helper is handed only the names the process was started with. Any name
    introduced after startup could be a loader variable such as ``PYTHONPATH`` or
    ``LD_PRELOAD`` that would run code inside the helper, so the snapshot bounds
    what the helper inherits rather than trusting the live environment wholesale.
    With no snapshot taken the whole environment is trusted, which is what a plain
    ``dict(os.environ)`` says.
    """
    if _TRUSTED_VARS is None:
        return dict(os.environ)
    return {name: value for name, value in os.environ.items() if name in _TRUSTED_VARS}


def _neutral_working_directory(os_name: str = os.name) -> str:
    """The helper's working directory: anywhere but the project the client opened.

    Python puts the working directory on ``sys.path``, so inheriting it lets that
    project decide what ``python -m helper`` imports. See "Process lifecycle" in
    ``docs/credential-providers.md``.
    """
    if os_name == "nt":
        return os.environ.get("SystemRoot") or "C:\\"
    return "/"


def _resolve_executable(var: str, argv0: str, env: dict[str, str], logger: logging.Logger) -> str:
    """Resolve the helper to an absolute path under the executable contract.

    Absolute paths are taken as given. A bare name is looked up on the trusted
    ``PATH``. Anything else names a location relative to a working directory the
    operator did not choose, so it is refused rather than guessed.
    """
    if os.path.isabs(argv0):
        return argv0
    if os.path.dirname(argv0):
        _fail_secret(
            logger,
            "%s: %r is a relative path. Give the helper's absolute path, or a bare name found on PATH.",
            var,
            argv0,
        )
    # "" not None: shutil.which treats path=None as "read os.environ['PATH']",
    # which would bypass the trusted-name filter applied to build ``env``.
    found = shutil.which(argv0, path=env.get("PATH", ""))
    if found is None:
        _fail_secret(
            logger,
            "%s: %r was not found on PATH. Give the helper's absolute path.",
            var,
            argv0,
        )
    if not os.path.isabs(found):
        # An empty or "." PATH element resolves against the working directory
        # the MCP client chose; on Windows which() prepends it outright.
        _fail_secret(
            logger,
            "%s: %r resolved to %r, which is relative to the working directory. Give the helper's absolute path.",
            var,
            argv0,
            found,
        )
    return found


def _warn_if_others_can_write(var: str, executable: str, logger: logging.Logger) -> None:
    """Warn when anyone but the owner can rewrite the helper.

    The file provider warns about a secret others can read; a helper others can
    write is worse, because it runs as the server on every start.
    """
    if os.name == "nt":
        return
    for path in (executable, os.path.dirname(executable)):
        try:
            mode = os.stat(path).st_mode
        except OSError:
            continue
        if stat.S_ISDIR(mode) and mode & stat.S_ISVTX:
            # Sticky: only the owner can replace what is inside, so a 1777
            # directory such as /tmp is not an exposure here.
            continue
        if mode & 0o022:
            logger.warning(
                "[credentials] %s runs %s, which is writable by other users (mode %04o); "
                "anyone who can write it chooses what runs as this server.",
                var,
                path,
                mode & 0o777,
            )


def _terminate_process_tree(proc: subprocess.Popen, var: str, name: str, logger: logging.Logger) -> bool:
    """Terminate the helper and everything it started. True if the tree is gone.

    The helper is its own session leader (POSIX) or process-group root
    (Windows), so a background descendant holding the output pipe open is killed
    with it -- unless that descendant left the session on its own, which no
    signal here can reach. The caller words its message on the return value
    rather than asserting a termination that may not have happened.

    Reaping the direct child is not evidence about the group: a descendant that
    ignores SIGTERM outlives its parent. True therefore means the child was
    reaped *and* the group is empty.

    Two limits are known and deliberately not worked around. An unreaped zombie
    still answers ``killpg``, so where this process is PID 1 with no init reaping
    orphans (a container without ``init: true``) a dead tree can be reported as
    surviving -- a false negative on a path that refuses startup either way.
    And the group id is the reaped child's pid, so a full pid wrap inside the
    grace period could aim the second signal elsewhere; at default ``pid_max``
    that needs millions of forks in two seconds.
    """
    if os.name == "nt":
        # Absolute path and a neutral cwd for the same reason the helper gets
        # them: Windows searches the working directory ahead of PATH, and that
        # directory is the project the MCP client opened.
        taskkill = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "taskkill.exe")
        try:
            subprocess.run(
                [taskkill, "/T", "/F", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                cwd=_neutral_working_directory(),
                timeout=_SECRET_COMMAND_GRACE_S,
            )
        except subprocess.TimeoutExpired:
            pass
        except OSError as exc:
            # taskkill missing or blocked by policy. Kill the direct child at
            # least, rather than letting an OSError escape as something other
            # than the credential exit code.
            logger.warning(
                "[credentials] %s: could not run taskkill for %s (%s); killing the helper only.",
                var,
                name,
                exc.strerror or type(exc).__name__,
            )
            with contextlib.suppress(OSError):
                proc.kill()
        return _reap(proc, _SECRET_COMMAND_GRACE_S)
    # Popen(start_new_session=True) makes the helper's PID its process-group
    # ID. Keep targeting that group after the leader exits: getpgid(pid) can
    # fail for an exited leader while its descendants still hold stdout open.
    group = proc.pid
    # A descendant that re-parented itself out of the session is reached by
    # neither signal.
    #
    # The direct child exiting is not the tree dying: a descendant that ignores
    # SIGTERM stays in the group after its parent is reaped. Reap the child so
    # its own membership stops answering, then ask the group whether anything is
    # left, and only stop escalating once nothing is.
    reaped = False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return reaped or _reap(proc, _SECRET_COMMAND_REAP_S)
        except OSError:
            # EPERM: a helper that changed uid (sudo, doas, pkexec). Nothing to
            # signal, but startup must still refuse with the credential exit
            # code rather than a traceback. The group is still consulted: a
            # survivor we may not signal is exactly the case that must not be
            # reported as a terminated tree.
            reaped = reaped or _reap(proc, _SECRET_COMMAND_GRACE_S)
            return reaped and not _group_has_members(group)
        if not reaped:
            reaped = _reap(proc, _SECRET_COMMAND_GRACE_S)
        if _await_group_exit(group, _SECRET_COMMAND_GRACE_S):
            return reaped
    return False


def _group_has_members(group: int) -> bool:
    """Whether any process is still in *group*. EPERM counts as yes.

    Signal 0 delivers nothing and only reports reachability, so this asks the
    kernel rather than inferring group state from the processes we know about.
    """
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # EPERM: members exist, we simply may not signal them.
        return True
    return True


def _await_group_exit(group: int, timeout: float) -> bool:
    """Wait, bounded, for the group to empty.

    A signalled descendant stays visible until its parent reaps it, and the
    helper that would have done so is already gone -- so the group can hold a
    zombie for as long as init takes. Polling avoids reporting a survivor that
    is merely slow to disappear.
    """
    deadline = time.monotonic() + timeout
    while _group_has_members(group):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def _reap(proc: subprocess.Popen, timeout: float) -> bool:
    """Wait for the child, without touching its pipe.

    ``wait`` is ``waitpid``: a held-open pipe cannot block it, and closing the
    read end here would block instead whenever a reader still holds the buffer
    lock.
    """
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _warn_unverified_platform(var: str, logger: logging.Logger, os_name: str = os.name) -> None:
    """Say at runtime what the platform table says on paper."""
    if os_name == "nt":
        logger.warning(
            "[credentials] %s: the command provider is unverified on Windows. Its process-group cleanup and "
            "path handling have not been exercised there; UNIFI_<VAR>_FILE is the tested option on Windows.",
            var,
        )


def _run_secret_command(var: str, command: str, logger: logging.Logger) -> str:
    """Run *command* as an argv (no shell) and return its stdout.

    Nothing the helper writes is ever logged: it may print the credential to
    either stream, and a failing helper often does. The full contract is in
    ``docs/credential-providers.md``.
    """
    try:
        argv = shlex.split(command)
    except ValueError:
        _fail_secret(logger, "%s could not be parsed as a command line (check the quoting).", var)
    if not argv:
        _fail_secret(logger, "%s is set but contains no command.", var)

    env = _trusted_environ()
    executable = _resolve_executable(var, argv[0], env, logger)
    name = os.path.basename(executable)
    _warn_if_others_can_write(var, executable, logger)

    _warn_unverified_platform(var, logger)
    platform_kwargs: dict[str, Any] = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        # No shell is involved. stdin is closed because under stdio transport it
        # is the MCP client's JSON-RPC pipe and a prompting helper must not read
        # it. stderr is discarded rather than captured; see the docstring.
        proc = subprocess.Popen(  # noqa: S603 -- argv from the operator's own environment, never a shell
            [executable, *argv[1:]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            bufsize=0,
            stderr=subprocess.DEVNULL,
            cwd=_neutral_working_directory(),
            env=env,
            **platform_kwargs,
        )
    except OSError as exc:
        _fail_secret(logger, "%s: could not run %s (%s).", var, name, exc.strerror or type(exc).__name__)

    stdout, reason = _read_capped(proc, _SECRET_COMMAND_TIMEOUT_S)
    if reason == "deadline" or reason.startswith("error"):
        reaped = _terminate_process_tree(proc, var, name, logger)
        if reason.startswith("error"):
            _fail_secret(
                logger,
                "%s: could not read the output of %s (%s); its process tree %s.",
                var,
                name,
                reason.partition(":")[2] or "unknown",
                "was terminated" if reaped else "could not be fully terminated and may still be running",
            )
        _fail_secret(
            logger,
            "%s: %s did not finish within %ss; its process tree %s.",
            var,
            name,
            _SECRET_COMMAND_TIMEOUT_S,
            "was terminated" if reaped else "could not be fully terminated and may still be running",
        )
    if reason == "overrun":
        # Killed at the moment it overran rather than after the full timeout:
        # a helper writing without end would otherwise buffer until the server
        # is out of memory, long before it could refuse startup.
        _terminate_process_tree(proc, var, name, logger)
        _fail_secret(logger, "%s: %s produced more than %d bytes.", var, name, _SECRET_MAX_BYTES)

    if proc.returncode != 0:
        _fail_secret(
            logger,
            "%s: %s exited with status %s. Its output is not logged; run the helper yourself to see why.",
            var,
            name,
            proc.returncode,
        )
    try:
        # utf-8-sig drops a BOM left by editors that save "UTF-8 with BOM".
        return stdout.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail_secret(logger, "%s: %s produced output that is not valid UTF-8.", var, name)


def _read_capped(proc: subprocess.Popen, timeout: float, os_name: str = os.name) -> tuple[bytes | None, str]:
    """Read the helper's stdout under a deadline and a size cap.

    Returns ``(data, reason)`` where reason is ``eof`` (complete), ``overrun``
    (past the cap), ``deadline`` or ``error``. The cap is enforced while the
    helper runs rather than after it finishes, on every platform: a helper
    writing without end would otherwise buffer until the server is out of
    memory, long before the size check could refuse startup.
    """
    if proc.stdout is None:  # pragma: no cover - Popen was given stdout=PIPE
        return None, "error"
    deadline = time.monotonic() + timeout
    if os_name == "nt":
        return _read_capped_threaded(proc, deadline)
    fd = proc.stdout.fileno()
    captured = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return None, "deadline"
            try:
                chunk = os.read(fd, 65536)
            except OSError as exc:
                return None, f"error:{exc.strerror or type(exc).__name__}"
            if not chunk:
                break
            captured.extend(chunk)
            if len(captured) > _SECRET_MAX_BYTES:
                return bytes(captured), "overrun"
    # EOF is not exit: spend what is left of the same budget reaping, rather
    # than opening a second one.
    if not _reap(proc, max(0.0, deadline - time.monotonic())):
        return None, "deadline"
    return bytes(captured), "eof"


def _read_capped_threaded(proc: subprocess.Popen, deadline: float) -> tuple[bytes | None, str]:
    """The Windows read: selectors cannot wait on a pipe there.

    A reader thread is the only portable option, so it reads at most one byte
    past the cap and its pipe is never closed from this thread -- closing under
    a blocked reader is what makes the buffer lock unreleasable.

    Popen is given ``bufsize=0``, so stdout is a raw stream and one ``read(n)``
    returns only what has already arrived. A helper that writes, pauses, then
    writes again would otherwise have its first burst accepted as the whole
    credential -- a silent truncation rather than a refusal -- so read until EOF
    or the cap.
    """
    captured: list[bytes] = []

    def _drain() -> None:
        assert proc.stdout is not None
        chunks: list[bytes] = []
        remaining = _SECRET_MAX_BYTES + 1
        while remaining > 0:
            chunk = proc.stdout.read(remaining)
            if chunk is None:  # would-block on a non-blocking fd, not EOF
                continue
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        captured.append(b"".join(chunks))

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    reader.join(max(0.0, deadline - time.monotonic()))
    if reader.is_alive() or not captured:
        return None, "deadline"
    if len(captured[0]) > _SECRET_MAX_BYTES:
        return captured[0], "overrun"
    if not _reap(proc, max(0.0, deadline - time.monotonic())):
        return None, "deadline"
    return captured[0], "eof"


_SecretReader = Callable[[str, str, logging.Logger], str]

# Indirect spellings for a secret key, in the order they are reported.
_SECRET_READERS: tuple[tuple[str, _SecretReader], ...] = (
    ("_FILE", _read_secret_file),
    ("_COMMAND", _run_secret_command),
)


def _listed(names: list[str]) -> str:
    """``A and B are both``; ``A, B and C are all`` -- the subject and its verb agreement.

    Two names is the case that existed before the command provider, so it keeps
    upstream's exact sentence.
    """
    joined = " and ".join([", ".join(names[:-1]), names[-1]])
    return f"{joined} are both" if len(names) == 2 else f"{joined} are all"


def resolve_env(key: str, *, env_prefix: str, logger: logging.Logger) -> str | None:
    """Resolve one config key from the environment.

    Checks the server-specific level (``UNIFI_<PREFIX>_<KEY>``) and then the shared
    level (``UNIFI_<KEY>``). An empty variable counts as unset, so a plugin
    ``.mcp.json`` that interpolates ``"${UNIFI_NETWORK_PASSWORD:-}"`` does not shadow
    the shared level.

    Secret keys (by :func:`unifi_core.redaction.is_sensitive_key`: ``password``,
    ``api_key``) also accept two indirect spellings, whose value is the resolved
    secret with trailing newlines dropped:

    * ``<VAR>_FILE``     a path whose contents are the value
    * ``<VAR>_COMMAND``  an argv, run without a shell, whose stdout is the value

    Setting more than one spelling at one level, or an indirection that cannot be
    resolved, refuses startup with :data:`EXIT_SECRET_UNRESOLVED`.

    Returns:
        The resolved value, or ``None`` when nothing is set at either level.
    """
    upper = key.upper()
    secret = is_sensitive_key(key)
    for base in (f"UNIFI_{env_prefix}_{upper}", f"UNIFI_{upper}"):
        plain = os.getenv(base)
        indirect: list[tuple[str, str, _SecretReader]] = []
        if secret:
            for suffix, reader in _SECRET_READERS:
                indirect_var = f"{base}{suffix}"
                if raw := os.getenv(indirect_var):
                    indirect.append((indirect_var, raw, reader))
        spellings = ([base] if plain else []) + [var for var, _, _ in indirect]
        if len(spellings) > 1:
            _fail_secret(logger, "%s set; keep exactly one of them.", _listed([_origin(v) for v in spellings]))
        if plain:
            return plain
        if not indirect:
            continue
        var, raw, reader = indirect[0]
        if _TRUSTED_VARS is not None and var not in _TRUSTED_VARS:
            _fail_secret(
                logger,
                "%s was supplied by a .env file, not by the environment the server was started with; "
                "credential indirection is only honoured from the process environment.",
                var,
            )
        value = reader(var, raw, logger).rstrip("\r\n")
        if not value:
            _fail_secret(logger, "%s resolved to an empty value.", var)
        if "\n" in value:
            # A second line is not part of the secret; a wrong value accepted here
            # would surface later as an unexplained 401.
            _fail_secret(logger, "%s holds %d lines; expected exactly one.", var, value.count("\n") + 1)
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
    1. Explicit absolute path in the process environment variable ``CONFIG_PATH``
    2. Default ``config.yaml`` bundled within the package

    Never discover configuration in the working directory: an MCP client may
    choose a project controlled by someone other than the server operator.

    Then merges server-specific env vars (e.g. ``UNIFI_NETWORK_HOST``)
    with fallback to shared vars (e.g. ``UNIFI_HOST``) via :func:`resolve_env`.
    Secret keys may also be supplied as ``..._FILE`` or ``..._COMMAND``.

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
        if not path.is_absolute():
            logger.error("CONFIG_PATH must be an absolute path to an operator-controlled YAML file.")
            raise SystemExit(2)
        if path.exists() and path.is_file():
            resolved_path = path
            logger.info("Using configuration file from CONFIG_PATH: %s", path)
        else:
            logger.error("Configuration file specified by CONFIG_PATH not found: %s", path)
            raise SystemExit(2)
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
                if val == "???":
                    # OmegaConf's missing-value marker; it cannot be stored literally.
                    _fail_secret(logger, "the %s value '???' cannot be represented; choose another.", key)
                # Keep "${" literal: a generated password may contain it, and a value
                # from a .env must not be able to interpolate other variables.
                val = _escape_interpolation(val)
            unifi_env_overrides[key] = val

    if unifi_env_overrides:
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

    Retained for server releases built before setup mode; current servers call
    :func:`unifi_mcp_shared.setup_required.serve_setup_required` instead, so the
    client sees a connected server that explains how to configure it rather
    than a failed one with no reason.

    Raises:
        SystemExit: with code 5 when host is unconfigured.
    """
    from unifi_mcp_shared.setup_required import controller_host_configured, setup_required_message

    if controller_host_configured(cfg):
        return

    bar = "=" * 72
    logger.error(bar)
    logger.error("[%s] No controller host configured — refusing to start.", plugin_name)
    logger.error("")
    for line in setup_required_message(
        plugin_name=plugin_name, env_prefix=env_prefix, report=_SETTINGS_REPORT
    ).splitlines():
        logger.error("%s", line)
    report = _SETTINGS_REPORT
    if report is not None and report.state in {"missing", "ignored"}:
        logger.error("%s names %s.", SETTINGS_FILE_VAR, report.path)
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
