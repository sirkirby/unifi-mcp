"""unifi-api CLI."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from unifi_api.config import ensure_db_encryption_key, load_config
from unifi_api.logging import configure_logging
from unifi_api.server import create_app

app = typer.Typer(no_args_is_help=True, help="UniFi rich HTTP API service.")
keys_app = typer.Typer(no_args_is_help=True, help="Manage API keys.")
db_app = typer.Typer(no_args_is_help=True, help="Database operations.")
graphql_typer = typer.Typer(no_args_is_help=True, help="GraphQL schema utilities.")
app.add_typer(keys_app, name="keys")
app.add_typer(db_app, name="db")
app.add_typer(graphql_typer, name="graphql")


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Override config http.host"),
    port: int | None = typer.Option(None, help="Override config http.port"),
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
) -> None:
    """Start the HTTP server."""
    cfg = load_config(config_path)
    configure_logging(cfg.logging.level)
    ensure_db_encryption_key(cfg.db.path)
    app_instance = create_app(cfg)
    uvicorn.run(app_instance, host=host or cfg.http.host, port=port or cfg.http.port, log_config=None)


@app.command()
def migrate(
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
) -> None:
    """Run alembic migrations to head. Bootstraps an admin key on first run."""
    import asyncio
    import os
    import subprocess
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import select

    from unifi_api.auth.api_key import generate_key, hash_key
    from unifi_api.db.engine import create_engine
    from unifi_api.db.models import ApiKey
    from unifi_api.db.session import get_sessionmaker

    cfg = load_config(config_path)
    ensure_db_encryption_key(cfg.db.path)

    env = dict(os.environ)
    env["UNIFI_API_DB_PATH"] = cfg.db.path
    alembic_cwd = Path(__file__).parent.parent.parent  # apps/api
    result = subprocess.run(["alembic", "upgrade", "head"], env=env, cwd=alembic_cwd, check=False)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    # Bootstrap admin key if api_keys is empty
    async def _maybe_bootstrap() -> str | None:
        engine = create_engine(cfg.db.path)
        sm = get_sessionmaker(engine)
        try:
            async with sm() as session:
                existing = (await session.execute(select(ApiKey))).first()
                if existing is not None:
                    return None
                material = generate_key()
                session.add(
                    ApiKey(
                        id=str(uuid.uuid4()),
                        prefix=material.prefix,
                        hash=hash_key(material.plaintext),
                        scopes="admin",
                        name="bootstrap-admin",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
            return material.plaintext
        finally:
            await engine.dispose()

    plaintext = asyncio.run(_maybe_bootstrap())
    if plaintext:
        bootstrap_file = Path(cfg.db.path).parent / "bootstrap-admin-key"
        try:
            bootstrap_file.parent.mkdir(parents=True, exist_ok=True)
            bootstrap_file.write_text(plaintext, encoding="utf-8")
            bootstrap_file.chmod(0o600)
        except OSError:
            bootstrap_file = None  # best-effort; log line is still authoritative
        typer.echo("=" * 60)
        typer.echo("Initial admin API key (shown once, save it now):")
        typer.echo(plaintext)
        if bootstrap_file is not None:
            typer.echo("")
            typer.echo(f"Also written to: {bootstrap_file}")
            typer.echo("Retrieve later with:")
            typer.echo("  docker compose -f docker/docker-compose-api.yml exec \\")
            typer.echo(f"    unifi-api-server cat {bootstrap_file}")
            typer.echo("Delete this file once you've saved the key in your password manager.")
        typer.echo("=" * 60)


@keys_app.command("create")
def keys_create(
    name: str = typer.Argument(..., help="Human-readable name for the key"),
    scopes: str = typer.Option("read", help="Comma-separated scopes: read,write,admin"),
    env: str = typer.Option("live", help="Key env: live or test"),
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
) -> None:
    """Create a new API key. Prints the plaintext exactly once."""
    import asyncio
    import uuid
    from datetime import datetime, timezone

    from unifi_api.auth.api_key import ApiKeyEnv, generate_key, hash_key
    from unifi_api.db.engine import create_engine
    from unifi_api.db.models import ApiKey
    from unifi_api.db.session import get_sessionmaker

    cfg = load_config(config_path)
    ensure_db_encryption_key(cfg.db.path)

    async def _create() -> str:
        engine = create_engine(cfg.db.path)
        sm = get_sessionmaker(engine)
        try:
            material = generate_key(env=ApiKeyEnv(env))
            async with sm() as session:
                session.add(
                    ApiKey(
                        id=str(uuid.uuid4()),
                        prefix=material.prefix,
                        hash=hash_key(material.plaintext),
                        scopes=scopes,
                        name=name,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
            return material.plaintext
        finally:
            await engine.dispose()

    plaintext = asyncio.run(_create())
    typer.echo("=" * 60)
    typer.echo(f"API key for '{name}' (shown once, save it now):")
    typer.echo(plaintext)
    typer.echo("=" * 60)


@keys_app.command("list")
def keys_list(
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
) -> None:
    """List API keys (prefix + scopes only; never plaintext)."""
    import asyncio

    from sqlalchemy import select

    from unifi_api.db.engine import create_engine
    from unifi_api.db.models import ApiKey
    from unifi_api.db.session import get_sessionmaker

    cfg = load_config(config_path)

    async def _list():
        engine = create_engine(cfg.db.path)
        sm = get_sessionmaker(engine)
        try:
            async with sm() as session:
                rows = (await session.execute(select(ApiKey).order_by(ApiKey.created_at))).scalars().all()
                return [(r.prefix, r.scopes, r.name, r.created_at, r.revoked_at) for r in rows]
        finally:
            await engine.dispose()

    rows = asyncio.run(_list())
    if not rows:
        typer.echo("(no keys)")
        return
    typer.echo(f"{'PREFIX':<18} {'SCOPES':<22} {'NAME':<28} {'CREATED':<22} STATUS")
    for prefix, scopes, name, created, revoked in rows:
        status = "(revoked)" if revoked else "(active)"
        typer.echo(f"{prefix:<18} {scopes:<22} {name:<28} {created.isoformat()[:19]:<22} {status}")


@keys_app.command("revoke")
def keys_revoke(
    prefix: str = typer.Argument(..., help="Prefix of the key to revoke"),
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
) -> None:
    """Revoke an API key by prefix."""
    import asyncio
    from datetime import datetime, timezone

    from sqlalchemy import select

    from unifi_api.db.engine import create_engine
    from unifi_api.db.models import ApiKey
    from unifi_api.db.session import get_sessionmaker

    cfg = load_config(config_path)

    async def _revoke():
        engine = create_engine(cfg.db.path)
        sm = get_sessionmaker(engine)
        try:
            async with sm() as session:
                rows = (await session.execute(select(ApiKey).where(ApiKey.prefix == prefix))).scalars().all()
                if not rows:
                    return "not_found"
                if len(rows) > 1:
                    return "ambiguous"
                row = rows[0]
                if row.revoked_at is not None:
                    return "already_revoked"
                row.revoked_at = datetime.now(timezone.utc)
                await session.commit()
                return "ok"
        finally:
            await engine.dispose()

    result = asyncio.run(_revoke())
    if result == "not_found":
        typer.echo(f"no key with prefix '{prefix}'", err=True)
        raise typer.Exit(1)
    if result == "ambiguous":
        typer.echo(f"multiple keys match prefix '{prefix}' — be more specific", err=True)
        raise typer.Exit(1)
    if result == "already_revoked":
        typer.echo(f"key '{prefix}' was already revoked")
        return
    typer.echo(f"revoked key '{prefix}'. Note: revocation effective within 60 seconds against running services.")


@db_app.command("backup")
def db_backup(out_path: Path = typer.Argument(..., help="Backup destination")) -> None:
    """Encrypted backup."""
    typer.echo("(implemented in a later phase)")
    raise typer.Exit(code=0)


@db_app.command("rekey")
def db_rekey(new_key: str = typer.Argument(..., help="New passphrase")) -> None:
    """Rotate the column encryption key."""
    typer.echo("(implemented in a later phase)")
    raise typer.Exit(code=0)


@graphql_typer.command("scaffold-resource")
def graphql_scaffold_resource(
    product: str = typer.Argument(..., help="Product: network/protect/access"),
    resource: str = typer.Argument(..., help="Resource name (singular preferred): client, camera, door"),
    out_root: Path = typer.Option(
        Path("."),
        help=(
            "Repository root (defaults to cwd). Output goes under "
            "apps/api/src/unifi_api/graphql/types/<product>/<resource>.py"
        ),
    ),
) -> None:
    """Scaffold a starter Strawberry type for a resource.

    Generates a typed class with a from_manager_output(raw) classmethod and
    a to_dict() method. The maintainer fills in the typed fields and the
    coercion logic by inspecting the existing serializer at
    apps/api/src/unifi_api/serializers/<product>/<resource>.py.
    """
    if product not in ("network", "protect", "access"):
        typer.echo(f"unknown product: {product}", err=True)
        raise typer.Exit(2)

    pascal = "".join(p.capitalize() for p in resource.split("_"))
    template = f'''\
"""Strawberry type for {product}/{resource}.

Migrated from the dict-based serializer at
serializers/{product}/{resource}.py — the from_manager_output classmethod
contains the coercion logic that used to live in the serializer's
serialize() method.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


@strawberry.type(description="TODO: human-readable description for {pascal}.")
class {pascal}:
    # TODO: declare typed fields mirroring the serializer dict shape.
    # Use strawberry.ID for primary identifiers (mac, id, controller).
    pass

    @classmethod
    def from_manager_output(cls, raw: Any) -> "{pascal}":
        """Coerce a raw manager response into a typed {pascal}.

        Replaces the dict-shaping logic in serializers/{product}/{resource}.py.
        """
        # TODO: extract field values from `raw` and pass to cls(...).
        return cls()

    def to_dict(self) -> dict:
        """Project to dict for REST routes consuming via type_registry."""
        return asdict(self)
'''

    target_dir = out_root / "apps" / "api" / "src" / "unifi_api" / "graphql" / "types" / product
    target_file = target_dir / f"{resource}.py"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file.write_text(template, encoding="utf-8")
    typer.echo(f"wrote {target_file}")


if __name__ == "__main__":
    app()
