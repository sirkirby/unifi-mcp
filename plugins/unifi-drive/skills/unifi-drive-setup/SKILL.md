---
name: unifi-drive-setup
description: Configure the UniFi Drive plugin for Claude Code, Codex or OpenClaw — NAS host, local account, password provider, certificate pin and write permissions. Also use when the unifi-drive server is in setup mode, cannot log in to the NAS, or its tools are missing.
---

# Set up UniFi Drive

Ask one question at a time and wait for the answer. Never ask for a password
in chat, and never put one in a command argument, tool call or output.

1. **Choose the client.** Use Claude Code, Codex or OpenClaw. Other clients use
   the repository's native/manual server installation instructions; do not invent
   plugin configuration for them. Real-client acceptance of this bundle is not
   yet measured. Locate this installed plugin's root from the skill path.
2. **Check prerequisites.** Run `bash <plugin-root>/scripts/check-prereqs.sh --target <client>`
   or `& <plugin-root>/scripts/check-prereqs.ps1 -Target <client>` on Windows.
   Install `uv`/`uvx` and the chosen client CLI when missing. The server needs
   Python 3.13 or newer (uv can supply it); setup needs Python 3.11 or newer and
   falls back to uv. Stop on a non-zero exit and report it.
3. **Point at the NAS.** Ask for the IP address or hostname of the UniFi NAS
   itself (`UNIFI_DRIVE_HOST`), not the gateway: the NAS is a separate UniFi OS
   console. Ask for a local UniFi OS username on the NAS
   (`UNIFI_DRIVE_USERNAME`); a UI.com account with MFA cannot log in. A
   dedicated local account is best. Drive never uses the shared `UNIFI_HOST`,
   `UNIFI_USERNAME`, `UNIFI_PASSWORD`, `UNIFI_PORT` or `UNIFI_SSL_FINGERPRINT`
   and has no API key; setup refuses them. Never copy another plugin's
   credentials here.
4. **Save one password source.** Accept only `UNIFI_DRIVE_PASSWORD`,
   `UNIFI_DRIVE_PASSWORD_FILE` or `UNIFI_DRIVE_PASSWORD_COMMAND`; two nonempty
   forms are refused. Provider files must be nonempty readable absolute paths;
   command providers name an available executable and argv, run without a shell
   by the server and never prompting. Setup checks references without running a
   command provider or reading the file. Prefer a provider. In Claude Code the
   plugin's options dialog (`/plugin`, then `unifi-drive`, then Configure
   options) also offers a masked password field stored in the system keychain.
   A raw password otherwise travels only as a JSON patch on stdin
   (`--input-json` / `-InputJson`) from a local masked prompt or secret manager.
   Switching away from a keychain-held password may need a newer Claude Code or
   a reinstall; follow the helper's value-free guidance rather than saving two
   forms.
5. **Optional settings.** Defaults: port `443`, SSL verification off, lazy tool
   loading. To customize, set `UNIFI_DRIVE_PORT`, `UNIFI_DRIVE_VERIFY_SSL` or
   `UNIFI_TOOL_REGISTRATION_MODE`. A certificate pin checks the NAS even on its
   factory self-signed certificate. Get it with the host and port, show it to
   the user to confirm, and save it as `UNIFI_DRIVE_SSL_FINGERPRINT`:

   ```bash
   openssl s_client -connect <host>:<port> </dev/null 2>/dev/null \
     | openssl x509 -noout -fingerprint -sha256
   ```

   A pin overrides SSL verification and fails once the NAS certificate changes,
   until it is updated.
6. **Write permissions.** Every write stays off unless the user opts in, and
   keep `UNIFI_DRIVE_TOOL_PERMISSION_MODE=confirm` so each one is previewed.
   Turning SMB, NFS or Time Machine on or off and changing an NFS client are
   updates; adding a client is a create; removing one is a delete. Tell the user
   that turning SMB off also stops Time Machine. Claude Code's options hold only
   the server-level gates `UNIFI_POLICY_DRIVE_CREATE`, `UNIFI_POLICY_DRIVE_UPDATE`
   and `UNIFI_POLICY_DRIVE_DELETE`. Codex and OpenClaw also take category gates
   that override them: `UNIFI_POLICY_DRIVE_FILE_SERVICES_UPDATE` and
   `UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_<CREATE|UPDATE|DELETE>`. For read-only
   setup, set all three server-level gates to `false`.
7. **Write the configuration.** Pass only values the user gave or chose:

   ```bash
   bash <plugin-root>/scripts/set-env.sh --target <claude|codex|openclaw> \
     UNIFI_DRIVE_HOST=<nas-host> \
     UNIFI_DRIVE_USERNAME=<local-user> \
     'UNIFI_DRIVE_PASSWORD_FILE=<absolute-path>' \
     UNIFI_DRIVE_TOOL_PERMISSION_MODE=confirm \
     UNIFI_POLICY_DRIVE_CREATE=false \
     UNIFI_POLICY_DRIVE_UPDATE=false \
     UNIFI_POLICY_DRIVE_DELETE=false
   ```

   On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target <client> ...` with
   the same `KEY=VALUE` arguments. Use `--input-json` for a raw password or a
   null deletion, and `--dry-run` / `-DryRun` to validate without saving.
   Claude Code saves the plugin's options through `claude plugin configure`
   (values on stdin; a raw password goes to the keychain); they apply in every
   project. Codex and OpenClaw save to the private per-user file
   `~/.config/unifi-mcp/drive.env` (Windows:
   `%USERPROFILE%\.config\unifi-mcp\drive.env`), which the bundled
   `.mcp.codex.json` names through `UNIFI_SETTINGS_FILE`; setup creates no MCP
   client entry. If a manual `unifi-drive` entry shadows the bundle, remove it
   with the client editor and rerun. No earlier plugin version kept Drive
   settings, so there is nothing to migrate or refresh.
8. **Reconnect and verify.** Claude Code: `/reload-plugins` or a new session
   loads the options; use `/mcp reconnect plugin:unifi-drive:unifi-drive` only
   if `/mcp` shows the server as failed. Codex: restart Codex. OpenClaw: start a
   new session or run `openclaw gateway restart`. Drive has no startup login:
   the server starts without contacting the NAS, so a running server does not
   prove the host or password. Verify with one read, `drive_get_system_info`,
   and report only the console's name, model and firmware. A login failure
   there means the host, the local account or the password source is wrong;
   correct it and rerun step 7. A server offering only its setup-status tool
   has no host saved yet.

On a validation or write failure the previous settings stay in place. After a
forced termination, remove adjacent `.setup-lock` and `.unifi-setup-*` staging
entries only once no setup is running, without displaying their contents.
