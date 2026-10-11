#!/usr/bin/env python3
"""Check that tool names in shipped plugin files exist in the releases plugins pin.

Every ``unifi_``/``protect_``/``access_`` name in a plugin's files must exist in
the ``tools_manifest.json`` of the server release that the product's plugin pins,
read from that release tag in git. That is what users actually run. Cross-product
skills may also name tools served by the latest released relay.

Uses only the standard library, like ``plugin_versions.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from plugin_versions import git, latest_tag, pin_tag, plugin_state

PREFIXES = {"unifi": "network", "protect": "protect", "access": "access"}
TOOL_NAME = re.compile(r"(?<![\w./-])(unifi|protect|access)_[a-z0-9_]*[a-z0-9](?![\w-])")
# Every server registers these meta-tools, whatever its manifest lists.
META_TOOLS = ("tool_index", "execute", "batch", "batch_status", "load_tools")
# Prefixed identifiers that are not tools: Access event types and topics, and field names.
NOT_TOOLS = frozenset({"access_granted", "access_denied", "access_denial", "access_end", "protect_camera_id"})
RELAY_SOURCE = "packages/unifi-mcp-relay/src/"
RELAY_TOOL = re.compile(r'^TOOL_NAME = "([a-z0-9_]+)"$', re.MULTILINE)


@dataclass
class Release:
    """Tool names one release serves, and where they came from."""

    source: str
    tools: set[str] = field(default_factory=set)


def tag_exists(root: Path, tag: str) -> bool:
    try:
        git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    except ValueError:
        return False
    return True


def pinned_release(root: Path, product: str) -> Release:
    """Read the tool manifest from the release tag the product's plugin pins."""
    bundle = root / "plugins" / f"unifi-{product}"
    if not bundle.is_dir():
        raise ValueError(f"no unifi-{product} plugin pins a {product} release")
    package = f"unifi-{product}-mcp"
    version = plugin_state(bundle)[1].get(package)
    if version is None:
        raise ValueError(f"unifi-{product}: no {package} pin")
    tag = pin_tag(package, version)
    if not tag_exists(root, tag):
        if product == "network" and tag_exists(root, f"v{version}"):
            tag = f"v{version}"
        else:
            raise ValueError(f"unifi-{product}: pinned release tag {tag} is missing; fetch tags (git fetch --tags)")
    path = f"apps/{product}/src/unifi_{product}_mcp/tools_manifest.json"
    try:
        manifest = json.loads(git(root, "show", f"{tag}:{path}"))
    except ValueError as exc:
        raise ValueError(f"unifi-{product}: release {tag} has no {path}") from exc
    tools = {tool["name"] for tool in manifest["tools"]}
    prefix = next(p for p, owner in PREFIXES.items() if owner == product)
    return Release(f"{tag} (pinned by unifi-{product})", tools | {f"{prefix}_{meta}" for meta in META_TOOLS})


def relay_release(root: Path) -> Release:
    """Read tool names from the latest released relay's source."""
    version = latest_tag(set(git(root, "tag", "--list", "relay/v*").splitlines()), "relay")
    if version is None:
        return Release("no released relay (no relay/v* tag; fetch tags)")
    tag = f"relay/v{version}"
    tools = set()
    for path in git(root, "ls-tree", "-r", "--name-only", tag, "--", RELAY_SOURCE).splitlines():
        if path.endswith(".py"):
            tools.update(RELAY_TOOL.findall(git(root, "show", f"{tag}:{path}")))
    return Release(f"relay {tag}", tools)


def workspace_modules(root: Path) -> set[str]:
    """Python import names of workspace packages, which share the tool prefixes."""
    return {path.parent.name for path in root.glob("*/*/src/*/__init__.py")}


def check(root: Path) -> int:
    """Raise ValueError listing every unknown tool name; return the number of names checked."""
    releases: dict[str, Release] = {}
    relay: Release | None = None
    ignored = NOT_TOOLS | workspace_modules(root)
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for bundle in sorted(path for path in (root / "plugins").iterdir() if path.is_dir()):
        for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for match in TOOL_NAME.finditer(line):
                    name = match[0]
                    if name in ignored:
                        continue
                    seen.add((bundle.name, name))
                    product = PREFIXES[match[1]]
                    if product not in releases:
                        releases[product] = pinned_release(root, product)
                    sources = [releases[product]]
                    if bundle.name == "cross-product":
                        relay = relay or relay_release(root)
                        sources.append(relay)
                    if not any(name in release.tools for release in sources):
                        where = path.relative_to(root)
                        checked = " or ".join(release.source for release in sources)
                        errors.append(f"{where}:{lineno}: {name} is not a tool in {checked}")
    if errors:
        raise ValueError("unknown tool references:\n  " + "\n  ".join(errors))
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        count = check(args.root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Plugin tool reference check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Plugin tool references match pinned releases ({count} bundle/tool references)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
