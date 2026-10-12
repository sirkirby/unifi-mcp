#!/usr/bin/env python3
"""Start the server package that this plugin version pins, for the Codex setup entry.

Codex installs each plugin version in its own directory and deletes the previous
one on upgrade. The entry that setup writes keeps its saved environment and runs
a short stub that finds the installed version and runs this file, so the server
follows plugin upgrades. Standard library only; never prints configuration.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def fail(message):
    print("ERROR: " + message, file=sys.stderr)
    return 1


def main():
    root = Path(__file__).resolve().parent.parent
    try:
        servers = json.loads((root / ".mcp.codex.json").read_text(encoding="utf-8"))["mcpServers"]
        (server,) = servers.values()
        command, args = server["command"], server["args"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return fail("The installed plugin's server definition is missing or malformed; reinstall the plugin.")
    if command != "uvx" or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return fail("The installed plugin's server definition is malformed; reinstall the plugin.")
    executable = shutil.which("uvx")
    if executable is None:
        return fail("uvx is required; install uv from https://astral.sh/uv/install.sh and restart Codex.")
    argv = [executable, *args]
    if os.name == "nt":
        # Windows has no exec: stay the parent so Codex tracks the server's lifetime.
        return subprocess.call(argv)
    os.execv(executable, argv)


if __name__ == "__main__":
    sys.exit(main())
