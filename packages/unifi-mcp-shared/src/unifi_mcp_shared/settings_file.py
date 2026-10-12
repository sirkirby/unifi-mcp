"""Per-user settings file named by ``UNIFI_SETTINGS_FILE``.

Clients without per-user server options (Codex plugins) run the plugin's own
server entry and point it at a file the user's setup wrote. Accepted keys are
applied to the process environment before anything reads configuration, so
every reader -- ``resolve_env`` and its ``_FILE``/``_COMMAND`` providers, policy
gates, permission and registration mode, YAML ``oc.env`` interpolation --
treats them exactly as exported variables. The process environment wins.

This is not project ``.env`` discovery: the path is set explicitly by the
operator's client entry, must be absolute, and the file must belong to the
current user. Values are never logged; messages name the variable, the path,
a key, or a line number only.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_FILE_VAR = "UNIFI_SETTINGS_FILE"

_MAX_BYTES = 1024 * 1024
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class SettingsFileReport:
    """What loading the settings file did, for logging once logging exists.

    ``state`` is ``unset``, ``loaded``, ``missing`` or ``ignored``.
    """

    state: str = "unset"
    path: str | None = None
    messages: list[tuple[int, str, tuple[object, ...]]] = field(default_factory=list)

    def note(self, level: int, message: str, *args: object) -> None:
        self.messages.append((level, message, args))


def parse_settings(text: str, report: SettingsFileReport) -> dict[str, str]:
    """Parse dotenv-style ``KEY=VALUE`` lines, keeping only ``UNIFI_`` keys.

    Blank lines and ``#`` comments are skipped. One pair of matching quotes
    around a value is removed; nothing else is interpreted (no ``export``, no
    interpolation, no continuation lines, no inline comments).
    """
    settings: dict[str, str] = {}
    # Split on "\n" only: splitlines() would also break a value at form feeds
    # and Unicode separators, and number lines differently from an editor.
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not _KEY.fullmatch(key) or "\0" in value:
            report.note(logging.WARNING, "[settings] %s line %d is not KEY=VALUE; ignored.", SETTINGS_FILE_VAR, number)
            continue
        if value[:1] in {'"', "'"}:
            if len(value) < 2 or value[-1] != value[0]:
                report.note(
                    logging.WARNING, "[settings] %s line %d has an unclosed quote; ignored.", SETTINGS_FILE_VAR, number
                )
                continue
            value = value[1:-1]
        if not key.startswith("UNIFI_"):
            report.note(logging.WARNING, "[settings] %s: %s is not a UNIFI_ setting; ignored.", SETTINGS_FILE_VAR, key)
            continue
        if key == SETTINGS_FILE_VAR:
            report.note(logging.WARNING, "[settings] %s cannot name another settings file; ignored.", SETTINGS_FILE_VAR)
            continue
        settings[key] = value
    return settings


def _concern(info: os.stat_result, os_name: str) -> tuple | None:
    """An error (refuse the file), a warning (use it anyway), or ``None``.

    Checked on the open descriptor, so the file judged is the file read.
    """
    if not stat.S_ISREG(info.st_mode):
        return (logging.ERROR, "which is not a regular file; ignoring it.")
    if os_name == "nt":
        # No POSIX owner or mode bits to check; Windows ACLs are left to the user profile.
        return None
    mode = info.st_mode & 0o777
    if info.st_uid != os.geteuid():
        return (logging.ERROR, "which is not owned by the current user; ignoring it.")
    if mode & 0o022:
        return (logging.ERROR, "with mode %04o, which other users can write; ignoring it. Run chmod 600.", mode)
    if mode & 0o044:
        return (logging.WARNING, "with mode %04o; consider chmod 600 so other users cannot read it.", mode)
    return None


def _read_capped(fd: int) -> bytes:
    chunks: list[bytes] = []
    remaining = _MAX_BYTES + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read(path: Path, report: SettingsFileReport, os_name: str) -> str | None:
    """Read the file after checking who controls it, or record why not."""
    try:
        # Non-blocking so a FIFO cannot stall startup before fstat refuses it.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    except FileNotFoundError:
        report.state = "missing"
        report.note(logging.INFO, "[settings] %s names %s, which does not exist yet.", SETTINGS_FILE_VAR, path)
        return None
    except OSError as exc:
        report.state = "ignored"
        report.note(
            logging.ERROR,
            "[settings] %s names %s, which could not be opened (%s); ignoring it.",
            SETTINGS_FILE_VAR,
            path,
            exc.strerror or type(exc).__name__,
        )
        return None
    try:
        concern = _concern(os.fstat(fd), os_name)
        if concern is not None:
            level, message, *args = concern
            report.note(level, "[settings] %s names %s, " + message, SETTINGS_FILE_VAR, path, *args)
            if level >= logging.ERROR:
                report.state = "ignored"
                return None
        data = _read_capped(fd)
    except OSError as exc:
        report.state = "ignored"
        report.note(
            logging.ERROR,
            "[settings] %s names %s, which could not be read (%s); ignoring it.",
            SETTINGS_FILE_VAR,
            path,
            exc.strerror or type(exc).__name__,
        )
        return None
    finally:
        os.close(fd)
    if len(data) > _MAX_BYTES:
        report.state = "ignored"
        report.note(
            logging.ERROR,
            "[settings] %s names %s, which is larger than %d bytes; ignoring it.",
            SETTINGS_FILE_VAR,
            path,
            _MAX_BYTES,
        )
        return None
    try:
        # utf-8-sig drops a BOM left by editors that save "UTF-8 with BOM".
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.state = "ignored"
        report.note(
            logging.ERROR, "[settings] %s names %s, which is not valid UTF-8; ignoring it.", SETTINGS_FILE_VAR, path
        )
        return None


def apply_settings_file(
    environ: dict[str, str] | os._Environ = os.environ, os_name: str = os.name
) -> SettingsFileReport:
    """Load the file named by ``UNIFI_SETTINGS_FILE`` into *environ*.

    A variable already present in *environ* is kept. Every failure leaves
    *environ* untouched and is recorded on the returned report; nothing here
    exits or raises for a bad file.
    """
    report = SettingsFileReport()
    raw = environ.get(SETTINGS_FILE_VAR, "")
    if not raw:
        return report
    try:
        path = Path(raw).expanduser()
    except RuntimeError:
        report.state = "ignored"
        report.note(
            logging.ERROR,
            "[settings] %s starts with ~ but the home directory could not be determined; ignoring it.",
            SETTINGS_FILE_VAR,
        )
        return report
    report.path = str(path)
    if not path.is_absolute():
        report.state = "ignored"
        report.note(logging.ERROR, "[settings] %s must be an absolute path; ignoring %s.", SETTINGS_FILE_VAR, raw)
        return report
    text = _read(path, report, os_name)
    if text is None:
        return report
    settings = parse_settings(text, report)
    kept = [key for key in settings if key in environ]
    for key, value in settings.items():
        if key not in environ:
            environ[key] = value
    report.state = "loaded"
    report.note(
        logging.INFO,
        "[settings] Loaded %d setting(s) from %s (%s)%s.",
        len(settings) - len(kept),
        SETTINGS_FILE_VAR,
        path,
        f"; the process environment already sets {', '.join(sorted(kept))}" if kept else "",
    )
    return report
