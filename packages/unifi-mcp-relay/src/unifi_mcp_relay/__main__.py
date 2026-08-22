"""Entry point for ``python -m unifi_mcp_relay``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="unifi-mcp-relay",
        description="Bridge local UniFi MCP servers to a configured UniFi MCP relay worker.",
    )


def main(argv: list[str] | None = None) -> None:
    _build_parser().parse_args(argv)

    load_dotenv()
    # Under an installed package, the default search starts in site-packages.
    # Also load the project-local file without overriding real environment vars.
    load_dotenv(Path.cwd() / ".env", override=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    from unifi_mcp_relay.config import load_config
    from unifi_mcp_relay.main import RelaySidecar

    try:
        config = load_config()
    except ValueError as e:
        logging.error("Configuration error: %s", e)
        sys.exit(1)

    sidecar = RelaySidecar(config)
    try:
        asyncio.run(sidecar.run())
    except KeyboardInterrupt:
        logging.info("Shutting down...")


if __name__ == "__main__":
    main()
