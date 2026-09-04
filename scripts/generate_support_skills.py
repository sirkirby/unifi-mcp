#!/usr/bin/env python3
"""Generate product-qualified support-bundle skills from one safety workflow."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_URL = "https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md"


@dataclass(frozen=True)
class Product:
    slug: str
    label: str
    tool: str
    setup_skill: str


PRODUCTS = (
    Product("network", "Network", "unifi_get_support_bundle", "unifi-network-setup"),
    Product("protect", "Protect", "protect_get_support_bundle", "unifi-protect-setup"),
    Product("access", "Access", "access_get_support_bundle", "unifi-access-setup"),
)


def render(product: Product) -> str:
    resource_shape = (
        "\nFor a suspected Protect sensor serialization mismatch, explain that "
        '`resource_shape(resource="sensors")` is conditional and currently returns '
        "`unsupported` unless the installed server has a verified safe sensor-shape source. "
        "Ask before calling it. Do not claim UP-AirQuality or issue #523 coverage when it is unsupported.\n"
        if product.slug == "protect"
        else ""
    )
    return f"""---
name: unifi-{product.slug}-support
description: >-
  Generate a sanitized UniFi {product.label} support bundle, help the user review it locally,
  and prepare it for a bug report without posting it
---

# Prepare a UniFi {product.label} Support Bundle

Use `{product.tool}` to collect the smallest useful, sanitized support bundle. The server
returns JSON only to the configured MCP client; this skill never posts, uploads, comments,
or opens an issue for the user.

## Choose the Probe

- Start with `summary`. It is local/cache-only and does not contact the controller.
- Use `connectivity` only when connection or authentication behavior is relevant. Explain
  that it makes one bounded read-only request through the existing authenticated session,
  then ask for explicit confirmation before calling it.
{resource_shape}
If the user asks "show me what will be collected first," explain the selected probe and
the included/excluded data classes before invoking the tool.

## Generate

Call `{product.tool}(probe="summary")` unless the user selected and confirmed another
supported probe. Never route this tool through `*_execute`, `*_batch`, a relay, or a
multi-location fan-out.

If the tool is missing, recommend updating the `{product.slug}` plugin or package and
restarting the MCP client. If the server cannot start or register tools, use
`${product.setup_skill}` for setup help and fall back to the bug form's manual version,
controller, install, client, expected, actual, and reproduction fields. Do not ask for
credentials, raw configuration, controller payloads, or broad diagnostic logs.

## Review Locally

Show the complete returned JSON to the user and pause before any external sharing. Tell them:

- The bundle is sanitized, not anonymous. Package/controller versions, runtime modes,
  capability flags, and coarse structural shapes can correlate or fingerprint an environment.
- It excludes credentials, controller addresses, identifiers, raw resource values,
  response bodies, raw exception text, logs, configuration files, and caller-supplied
  paths or endpoints.
- `UNIFI_MCP_DIAGNOSTICS` logs are a separate operator facility and are not automatically safe to post publicly.
- They may remove optional sections or values they do not want to share, while keeping
  `schema_version`, `product`, `probe`, and the relevant evidence when possible.

Ask the user to confirm they reviewed the JSON and did not manually add raw logs, payloads,
configuration, credentials, controller identifiers, or security-vulnerability details.

## Prepare for the Bug Report

After review, give the user either:

1. A fenced `json` block they can paste into the **Support bundle (optional)** bug-form field; or
2. A local `.json` file they can inspect before dragging into GitHub.

Dragging a file into GitHub begins publication/upload, and an attachment on a public issue
is publicly accessible. Do not recommend screenshots of JSON. This support skill must never
upload, attach, paste, post, or submit the bundle. Return only the reviewed JSON or its local
path; any publication must happen outside this support workflow.

Canonical guide: {GUIDE_URL}
"""


def output_path(product: Product) -> Path:
    return ROOT / "plugins" / f"unifi-{product.slug}" / "skills" / f"unifi-{product.slug}-support" / "SKILL.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated skills differ")
    args = parser.parse_args()
    stale: list[str] = []
    for product in PRODUCTS:
        path = output_path(product)
        expected = render(product)
        if args.check:
            if not path.exists() or path.read_text() != expected:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected)
    if stale:
        parser.error("generated support skills are stale: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
