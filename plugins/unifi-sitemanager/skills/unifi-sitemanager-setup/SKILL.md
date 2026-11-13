---
name: unifi-sitemanager-setup
description: Configure the UniFi Site Manager plugin for Claude Code, Codex or OpenClaw, including keyless startup, credential providers, setup errors and reconnecting after a key change.
---

# Set up UniFi Site Manager

1. **Choose the client.** Use Claude Code, Codex or OpenClaw. Other clients use
   the repository's native/manual server installation instructions; do not invent
   plugin configuration for them. Real-client acceptance of this bundle is not
   yet measured. Locate this installed plugin's root from the skill path.
2. **Check prerequisites.** Run `bash <plugin-root>/scripts/check-prereqs.sh --target <client>`
   or `& <plugin-root>/scripts/check-prereqs.ps1 -Target <client>` on Windows.
   Install `uv`/`uvx` and the chosen client CLI when missing. The server needs
   Python 3.13 or newer (uv can supply it); setup needs Python 3.11 or newer and
   falls back to uv. Internet access to Ubiquiti's `https://api.ui.com` is required.
3. **Explain the scope.** A Site Manager API key grants visibility across the
   whole UniFi account. Ask the user to create a cloud key in Site Manager and
   choose exactly one source below. Never ask for the value in chat. This server
   has no console host, username, password, port, site or TLS setting and no
   permission or policy options. Never reuse or migrate `UNIFI_API_KEY` or a
   console credential.
4. **Save the one credential.** Accept only `UNIFI_SITEMANAGER_API_KEY`,
   `UNIFI_SITEMANAGER_API_KEY_FILE` or `UNIFI_SITEMANAGER_API_KEY_COMMAND`.
   Two nonempty forms are refused. Provider files must be nonempty readable
   absolute paths; command providers name an available executable and argv,
   run without a shell by the server. Setup validates references without running
   a command provider or reading the key file's contents.

   Claude Code's plugin options offer a sensitive masked API key field, stored
   in its system keychain, and file/command fields. Prefer a provider. For Codex
   and OpenClaw, use a provider reference with the bundled settings script:

   ```bash
   bash <plugin-root>/scripts/set-env.sh --target codex UNIFI_SITEMANAGER_API_KEY_FILE=/absolute/path/to/key
   ```

   ```powershell
   & <plugin-root>/scripts/set-env.ps1 -Target codex UNIFI_SITEMANAGER_API_KEY_FILE=C:\private\key
   ```

   Choose `claude` or `openclaw` instead when appropriate. The raw key must
   travel only as a JSON patch on stdin (`--input-json` / `-InputJson`) from
   a local masked prompt or secret manager. Never place it in a command argument,
   shell history, output, logs, or a conversation. If a masked input mechanism
   is unavailable, use a provider. Claude Code setup calls `claude plugin configure`
   with values on stdin, using the existing keychain mechanism. Switching from a
   keychain value may require clearing it in a newer Claude Code or reinstalling;
   follow the helper's value-free guidance rather than saving two forms.

   Codex and OpenClaw save only the key source in the private per-user file
   `~/.config/unifi-mcp/sitemanager.env` (Windows:
   `%USERPROFILE%\.config\unifi-mcp\sitemanager.env`). Their bundled
   `.mcp.codex.json` points there through `UNIFI_SETTINGS_FILE`; setup creates
   no MCP client entry. If a manual entry shadows the bundle, remove it with
   the client editor and rerun; Site Manager never migrates console settings.
5. **Reconnect.** Claude Code: `/reload-plugins` or start a new session to load
   new options; use `/mcp reconnect plugin:unifi-sitemanager:unifi-sitemanager`
   only if `/mcp` shows the server as failed. Codex: start a new session.
   OpenClaw: start a new session or restart the Gateway when an open session
   keeps the unconfigured server. Plugin upgrades take effect from the next agent turn. Codex setup warms the pinned package
   without a settings file or credential; it performs no authenticated read.
   With no key the server starts in keyless setup mode instead of connecting.
   Once the user agrees to an account-wide read, discover a bounded inventory
   read through the main `unifi-sitemanager` skill. Report only status and counts,
   never credential values. All domain tools read; there are no writes or
   support-bundle tool.
