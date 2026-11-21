#!/usr/bin/env python3
"""Generate the static tool manifest for unifi-innerspace-mcp.

Output: ``src/unifi_innerspace_mcp/tools_manifest.json``
"""

from __future__ import annotations

import sys
from pathlib import Path

from unifi_mcp_shared.manifest_generator import generate_and_write

if __name__ == "__main__":
    sys.exit(
        generate_and_write(
            project_root=Path(__file__).parent.parent,
            package="unifi_innerspace_mcp",
            tool_prefix="innerspace_",
            meta_prefix="innerspace",
            server_label="UniFi InnerSpace",
            fallback_label="InnerSpace",
            support_bundle=False,
        )
    )
