#!/usr/bin/env python3
"""Generate the static tool manifest for unifi-drive-mcp.

Output: ``src/unifi_drive_mcp/tools_manifest.json``
"""

from __future__ import annotations

import sys
from pathlib import Path

from unifi_mcp_shared.manifest_generator import generate_and_write

if __name__ == "__main__":
    sys.exit(
        generate_and_write(
            project_root=Path(__file__).parent.parent,
            package="unifi_drive_mcp",
            tool_prefix="drive_",
            meta_prefix="drive",
            server_label="UniFi Drive",
            fallback_label="Drive",
            support_bundle=False,
        )
    )
