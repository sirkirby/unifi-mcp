#!/bin/sh
# Claude Code SessionStart notice: warn when this project still holds the
# project-settings configuration that older plugin versions used, while the
# plugin's own options are unset. Reads key names only; never prints values.
case "$1" in
  network) label='UniFi Network'; upper=NETWORK ;;
  protect) label='UniFi Protect'; upper=PROTECT ;;
  access) label='UniFi Access'; upper=ACCESS ;;
  *) exit 0 ;;
esac
[ -n "${CLAUDE_PLUGIN_OPTION_HOST:-}" ] && exit 0
settings="${CLAUDE_PROJECT_DIR:-.}/.claude/settings.local.json"
[ -f "$settings" ] || exit 0
grep -Eq "\"UNIFI_(POLICY_)?${upper}_[A-Z0-9_]*\"[[:space:]]*:" "$settings" 2>/dev/null || exit 0
plugin="unifi-$1"
printf '{"systemMessage":"%s plugin: this project'"'"'s .claude/settings.local.json still holds UNIFI_%s_* settings, which this plugin version no longer reads, so the %s server starts unconfigured. Ask Claude to run the %s-setup migration (set-env.sh --target claude --migrate), then run /mcp reconnect plugin:%s:%s.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The %s plugin has no Claude Code options set, but this project has legacy UNIFI_%s_* settings in .claude/settings.local.json that the plugin no longer reads. Before using %s tools, offer to run the %s-setup skill migration: the plugin scripts/set-env.sh with --target claude --migrate. Never print those settings or their values."}}\n' \
  "$label" "$upper" "$plugin" "$plugin" "$plugin" "$plugin" "$plugin" "$upper" "$label" "$plugin"
exit 0
