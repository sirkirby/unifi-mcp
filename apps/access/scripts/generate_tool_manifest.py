#!/usr/bin/env python3
"""Generate the static tool manifest for unifi-access-mcp.

Output: ``src/unifi_access_mcp/tools_manifest.json``
"""

from __future__ import annotations

import sys
from pathlib import Path

from unifi_mcp_shared.manifest_generator import generate_and_write

if __name__ == "__main__":
    sys.exit(
        generate_and_write(
            project_root=Path(__file__).parent.parent,
            package="unifi_access_mcp",
            tool_prefix="access_",
            meta_prefix="access",
            server_label="UniFi Access",
            fallback_label="Access",
        )
    )
