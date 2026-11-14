#!/bin/sh
# Account-key setup notice only; never inspect console or project credentials.
[ "$1" = sitemanager ] || exit 0
if [ -n "${CLAUDE_PLUGIN_OPTION_API_KEY:-}${CLAUDE_PLUGIN_OPTION_API_KEY_FILE:-}${CLAUDE_PLUGIN_OPTION_API_KEY_COMMAND:-}" ]; then
  exit 0
fi
printf '%s\n' '{"systemMessage":"UniFi Site Manager uses one cloud account key. If setup is needed, use the unifi-sitemanager-setup skill and then /reload-plugins or start a new session.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Site Manager reads the whole account through api.ui.com. Configure exactly one cloud key source through the plugin options; never reuse console credentials or print a key. Use /mcp reconnect plugin:unifi-sitemanager:unifi-sitemanager only if the server is shown as failed."}}'
