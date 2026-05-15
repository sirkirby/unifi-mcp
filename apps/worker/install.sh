#!/usr/bin/env bash
set -euo pipefail

COMMAND="${1:-install}"

echo ""
echo "  UniFi MCP Worker CLI"
echo ""

# Check Node.js
if ! command -v node &>/dev/null; then
    echo "  Error: Node.js is required but not installed."
    echo "  Install it from https://nodejs.org/ or via your package manager:"
    echo "    brew install node      (macOS)"
    echo "    apt install nodejs     (Debian/Ubuntu)"
    echo "    winget install Volta   (Windows)"
    echo ""
    exit 1
fi

# Check minimum Node version (18+)
NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "  Error: Node.js 18+ required. Found: $(node -v)"
    echo "  Update from https://nodejs.org/"
    exit 1
fi

echo "  Node.js $(node -v) detected."

# Install or update the CLI
if command -v unifi-mcp-worker &>/dev/null; then
    echo "  Updating unifi-mcp-worker CLI..."
    npm install -g unifi-mcp-worker@latest --silent 2>/dev/null || npm install -g unifi-mcp-worker@latest
else
    echo "  Installing unifi-mcp-worker CLI..."
    npm install -g unifi-mcp-worker --silent 2>/dev/null || npm install -g unifi-mcp-worker
fi

echo ""

# Run the requested command, passing through any additional args
shift 2>/dev/null || true
unifi-mcp-worker "$COMMAND" "$@"
