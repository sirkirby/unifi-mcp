#!/bin/sh
# Claude Code SessionStart notice: warn when this project still holds the
# project-settings configuration that older plugin versions used. Reads key
# names only; never prints values.
case "$1" in
  network) label='UniFi Network'; upper=NETWORK ;;
  protect) label='UniFi Protect'; upper=PROTECT ;;
  access) label='UniFi Access'; upper=ACCESS ;;
  *) exit 0 ;;
esac
settings="${CLAUDE_PROJECT_DIR:-.}/.claude/settings.local.json"
[ -f "$settings" ] || exit 0
grep -Eq "\"UNIFI_(POLICY_)?${upper}_[A-Z0-9_]*\"[[:space:]]*:" "$settings" 2>/dev/null || exit 0
plugin="unifi-$1"
# A session started before the options changed keeps its old copy until
# /reload-plugins; a start failure cached with unchanged options needs a reconnect.
recover="run /reload-plugins, then /mcp reconnect plugin:$plugin:$plugin if /mcp still shows the server as failed"
if [ -n "${CLAUDE_PLUGIN_OPTION_HOST:-}" ]; then
  # Options apply in every project: this project's own settings are not in use.
  printf '{"systemMessage":"%s plugin: this project'"'"'s .claude/settings.local.json has its own UNIFI_%s_* settings, which this plugin version no longer reads, so the %s server uses the plugin options saved from another project, which may name a different controller. To make this project'"'"'s settings the options for every project, ask Claude to run the %s-setup migration with --replace (set-env.sh --target claude --migrate --replace), then %s. To keep the saved options, remove the leftover UNIFI_%s_* keys from that file.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The %s plugin options are set, but this project still holds its own legacy UNIFI_%s_* settings in .claude/settings.local.json, which the plugin no longer reads, so the %s server is using the options saved from another project, which may name a different controller. Before using %s tools, tell the user and offer the choice: migrate this project'"'"'s settings with the %s-setup skill (scripts/set-env.sh --target claude --migrate --replace), which makes them the options for every project, or remove the leftover UNIFI_%s_* keys to keep the saved options. Never print those settings or their values."}}\n' \
    "$label" "$upper" "$label" "$plugin" "$recover" "$upper" "$plugin" "$upper" "$label" "$label" "$plugin" "$upper"
  exit 0
fi
# Shared UNIFI_HOST makes the server fall back to the shared UNIFI_* keys in this
# file, which may name a different controller than the legacy product keys did.
if grep -Eq '"UNIFI_HOST"[[:space:]]*:' "$settings" 2>/dev/null; then
  effect="so the $label server will use the shared UNIFI_* settings in that file (UNIFI_HOST, ...), which may name a different controller, until you migrate"
  context="the plugin falls back to the shared UNIFI_* settings in that file (UNIFI_HOST, ...), which may name a different controller"
else
  effect="so the $label server starts unconfigured"
  context="the server starts unconfigured"
fi
printf '{"systemMessage":"%s plugin: this project'"'"'s .claude/settings.local.json still holds UNIFI_%s_* settings, which this plugin version no longer reads, %s. Ask Claude to run the %s-setup migration (set-env.sh --target claude --migrate), then %s.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The %s plugin has no Claude Code options set, but this project has legacy UNIFI_%s_* settings in .claude/settings.local.json that the plugin no longer reads, and %s. Before using %s tools, offer to run the %s-setup skill migration: the plugin scripts/set-env.sh with --target claude --migrate. Never print those settings or their values."}}\n' \
  "$label" "$upper" "$effect" "$plugin" "$recover" "$plugin" "$upper" "$context" "$label" "$plugin"
exit 0
