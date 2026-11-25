#!/bin/sh
# Setup notice only: no earlier plugin version kept Drive settings in the project,
# so there is nothing to migrate. Never inspect or print a credential.
[ "$1" = drive ] || exit 0
if [ -n "${CLAUDE_PLUGIN_OPTION_HOST:-}" ]; then
  exit 0
fi
printf '%s\n' '{"systemMessage":"UniFi Drive plugin: no NAS host is set. If setup is needed, use the unifi-drive-setup skill and then /reload-plugins or start a new session.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The UniFi Drive server connects to the NAS itself, a separate UniFi OS console from the gateway, with a local account on that NAS. Its host option is empty, so it starts in setup mode. Offer the unifi-drive-setup skill; never reuse the gateway host or shared console credentials, and never print a password. Use /mcp reconnect plugin:unifi-drive:unifi-drive only if the server is shown as failed."}}'
