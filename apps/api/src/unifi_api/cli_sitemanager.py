"""Cloud account CLI: secrets enter only through hidden input or standard input."""

import asyncio
import json
import sys
from pathlib import Path

import typer
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

from unifi_api.config import ApiConfig, ensure_db_encryption_key, load_config
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.engine import create_engine
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.sitemanager_errors import map_error
from unifi_api.services.sitemanager_management import manage_connection
from unifi_api.services.sitemanager_managers import SiteManagerFactory

app = typer.Typer(no_args_is_help=True, help="Manage the Site Manager cloud connection.")
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _key(key_stdin: bool) -> str:
    if key_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    return typer.prompt("Site Manager API key", hide_input=True)


def _run(config_path, operation, data=None):
    async def execute(cfg):
        engine = create_engine(cfg.db.path)
        factory = None
        try:
            cipher = ColumnCipher(derive_key(ApiConfig.read_db_key()))
            sm = get_sessionmaker(engine)
            factory = SiteManagerFactory(sm, cipher)
            payload = None
            if operation in ("create", "update"):
                model = SiteManagerConnectionCreate if operation == "create" else SiteManagerConnectionPatch
                payload = model.model_validate(data)
            return await manage_connection(sm, cipher, factory, operation, payload=payload, actor="(cli)")
        finally:
            if factory is not None:
                await factory.close()
            await engine.dispose()

    try:
        cfg = load_config(config_path)
        ensure_db_encryption_key(cfg.db.path)
        result = asyncio.run(execute(cfg))
    except Exception as exc:
        error = map_error(exc, "manage Site Manager connection", management=True)
    else:
        if result.data is not None:
            typer.echo(json.dumps(result.data))
        else:
            typer.echo("Site Manager connection deleted.")
        if result.status >= 400:
            raise typer.Exit(1)
        return
    if operation == "get" and error.kind == "sitemanager_not_configured":
        typer.echo("(no Site Manager connection)")
        return
    typer.echo(error.message, err=True)
    raise typer.Exit(1) from None


@app.command("add")
def add(
    name: str = typer.Option(..., help="Connection display name"),
    key_stdin: bool = typer.Option(False, help="Read the cloud key from one line of stdin"),
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
):
    _run(config_path, "create", {"name": name, "site_manager_api_key": _key(key_stdin)})


@app.command("update")
def update(
    name: str | None = typer.Option(None, help="Connection display name"),
    rotate_key: bool = typer.Option(False, help="Prompt for a replacement cloud key"),
    key_stdin: bool = typer.Option(False, help="Read a replacement cloud key from one line of stdin"),
    config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml"),
):
    data = {}
    if name is not None:
        data["name"] = name
    if rotate_key or key_stdin:
        data["site_manager_api_key"] = _key(key_stdin)
    _run(config_path, "update", data)


@app.command("list")
def list_connection(config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml")):
    _run(config_path, "get")


@app.command("delete")
def delete(config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml")):
    _run(config_path, "delete")


@app.command("probe")
def probe(config_path: Path = typer.Option(_DEFAULT_CONFIG_PATH, help="Path to config.yaml")):
    _run(config_path, "probe")
