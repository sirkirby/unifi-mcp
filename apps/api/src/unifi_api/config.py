"""Config loader for unifi-api.

YAML provides defaults; UNIFI_API_* env vars override.
The column encryption key is normally env-only (UNIFI_API_DB_KEY); for
zero-config local dev, `ensure_db_encryption_key` will auto-generate and
persist one inside the state volume if no env value is provided.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

import yaml
from omegaconf import OmegaConf


@dataclass(frozen=True)
class HttpConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class DbConfig:
    path: str = "/var/lib/unifi-api/state.db"


@dataclass(frozen=True)
class ApiConfig:
    http: HttpConfig
    logging: LoggingConfig
    db: DbConfig

    @staticmethod
    def read_db_key() -> str:
        key = os.environ.get("UNIFI_API_DB_KEY")
        if not key:
            raise RuntimeError(
                "UNIFI_API_DB_KEY environment variable is required. "
                "The unifi-api service refuses to start without an "
                "AES-GCM encryption key for sensitive columns."
            )
        return key


def load_config(yaml_path: Path) -> ApiConfig:
    """Load config from YAML, then layer in UNIFI_API_* env overrides."""
    base = OmegaConf.create(yaml.safe_load(yaml_path.read_text()) or {})
    env_overrides = OmegaConf.create(_extract_env_overrides())
    merged = OmegaConf.merge(base, env_overrides)
    container = OmegaConf.to_container(merged, resolve=True) or {}

    return ApiConfig(
        http=HttpConfig(
            host=str(container.get("http", {}).get("host", "0.0.0.0")),
            port=int(container.get("http", {}).get("port", 8080)),
            cors_origins=tuple(container.get("http", {}).get("cors_origins", []) or []),
        ),
        logging=LoggingConfig(
            level=str(container.get("logging", {}).get("level", "INFO")),
        ),
        db=DbConfig(
            path=str(container.get("db", {}).get("path", "/var/lib/unifi-api/state.db")),
        ),
    )


def _extract_env_overrides() -> dict:
    """Translate UNIFI_API_<SECTION>_<KEY> env vars into a nested dict."""
    overrides: dict = {}
    prefix = "UNIFI_API_"
    skip = {"UNIFI_API_DB_KEY"}  # handled separately, never put in config tree
    for full_key, value in os.environ.items():
        if not full_key.startswith(prefix) or full_key in skip:
            continue
        path = full_key[len(prefix) :].lower().split("_")
        if len(path) < 2:
            continue
        section, key = path[0], "_".join(path[1:])
        overrides.setdefault(section, {})[key] = _coerce_scalar(value)
    return overrides


def _coerce_scalar(s: str) -> str | int | bool:
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        return s


def ensure_db_encryption_key(db_path: str) -> str:
    """Return UNIFI_API_DB_KEY, auto-generating + persisting one if unset.

    Precedence:
      1. UNIFI_API_DB_KEY env var (production / CI / explicit override)
      2. <state_dir>/.db_encryption_key file (auto-generated on first boot)
      3. Generate a new 32-byte hex key, write it to (2), return it

    The auto-gen path makes local-dev zero-config — operators in production
    set the env var explicitly (often from a secret manager) and this
    function never touches the filesystem.

    Storing the auto-generated key inside the same volume as the encrypted
    SQLite file does not weaken the security model: the volume is already
    the trust boundary for the encrypted DB. Anyone with read access to
    the volume can read both files; an operator who wants stronger
    separation should set UNIFI_API_DB_KEY explicitly.

    Side effect: also sets os.environ["UNIFI_API_DB_KEY"] so downstream
    callers of ApiConfig.read_db_key() see the resolved value.
    """
    existing = os.environ.get("UNIFI_API_DB_KEY")
    if existing:
        return existing

    state_dir = Path(db_path).parent
    key_file = state_dir / ".db_encryption_key"

    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            os.environ["UNIFI_API_DB_KEY"] = key
            return key

    state_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    os.environ["UNIFI_API_DB_KEY"] = key
    logging.getLogger(__name__).info(
        "Auto-generated UNIFI_API_DB_KEY persisted to %s. Set UNIFI_API_DB_KEY explicitly to override.",
        key_file,
    )
    return key
