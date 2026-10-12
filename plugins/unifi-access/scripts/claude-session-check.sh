#!/bin/sh
# Claude Code SessionStart notice: warn when this project still holds the
# project-settings configuration that older plugin versions used. Compares the
# connection values with the saved options but never prints a value.
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
# A session keeps the options it started with: /mcp reconnect alone restarts the
# server with those, so new options need /reload-plugins or a new session.
recover="run /reload-plugins or start a new session (use /mcp reconnect plugin:$plugin:$plugin only if /mcp shows the server as failed)"
# Print the project's string or number value for key $1. Exit 2 when the key is
# absent and 1 when it is repeated or not a plain string, which counts as differing.
legacy_value() {
  tr '\r\n\t' '   ' <"$settings" | awk -v key="\"$1\"" '{
    s = $0; n = 0
    while ((i = index(s, key)) > 0) {
      s = substr(s, i + length(key))
      if (match(s, /^ *: */)) { n++; v = substr(s, RLENGTH + 1) }
    }
    if (n == 0) exit 2
    if (n > 1) exit 1
    if (match(v, /^"[^"]*"/)) {
      v = substr(v, 2, RLENGTH - 2)
      if (index(v, sprintf("%c", 92))) exit 1
      print v; exit 0
    }
    if (match(v, /^[0-9]+/)) { print substr(v, 1, RLENGTH); exit 0 }
    exit 1
  }'
}
# Normalize like setup: an empty value means the option default, and a port is
# compared as a number.
normalized() {
  value=$2
  [ -n "$value" ] || value=$3
  if [ "$1" = PORT ]; then
    value=$(printf '%s' "$value" | tr -d ' ')
    case "$value" in '' | *[!0-9]*) return 1 ;; esac
    value=$(printf '%s' "$value" | sed 's/^0*//')
    [ -n "$value" ] || value=0
  fi
  printf '%s' "$value"
}
# Print the connection variables whose project value is not the saved option: the
# host, whenever the project does not name one, and any other value the project
# holds that is repeated, not plain or unequal to the option. Names only.
differing_fields() {
  fields='HOST USERNAME PORT'
  [ "$1" = network ] && fields="$fields SITE"
  names=
  for field in $fields; do
    differs=
    case "$field" in PORT) default=443 ;; SITE) default=default ;; *) default= ;; esac
    legacy=$(legacy_value "UNIFI_${upper}_$field")
    status=$?
    if [ "$status" -eq 2 ]; then
      [ "$field" = HOST ] && differs=1
    elif [ "$status" -ne 0 ]; then
      differs=1
    else
      eval "option=\${CLAUDE_PLUGIN_OPTION_$field:-}"
      if legacy=$(normalized "$field" "$legacy" "$default") && option=$(normalized "$field" "$option" "$default"); then
        [ "$legacy" = "$option" ] || differs=1
      else
        differs=1
      fi
    fi
    [ -z "$differs" ] || names="${names:+$names, }UNIFI_${upper}_$field"
  done
  printf '%s' "$names"
}
if [ -n "${CLAUDE_PLUGIN_OPTION_HOST:-}" ]; then
  differing=$(differing_fields "$1")
  if [ -z "$differing" ]; then
    printf '{"systemMessage":"%s plugin: this project'"'"'s .claude/settings.local.json still holds UNIFI_%s_* settings, which this plugin version no longer reads. They name the same controller as the saved plugin options, so nothing changes. Remove the leftover UNIFI_%s_* keys from that file, or ask Claude to run the %s-setup migration (set-env.sh --target claude --migrate) to tidy up; the migration also copies this project'"'"'s other %s settings, such as its credential source, into the options for every project.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"This project still holds legacy UNIFI_%s_* settings in .claude/settings.local.json, which the %s plugin no longer reads. Their host, username, port and site equal the saved plugin options, so the %s server already uses the same controller. If the user asks, offer to remove the leftover keys or to run the %s-setup skill migration (scripts/set-env.sh --target claude --migrate), which also copies this project'"'"'s other settings, such as its credential source, into the options for every project. Never print those settings or their values."}}\n' \
      "$label" "$upper" "$upper" "$plugin" "$label" "$upper" "$plugin" "$label" "$plugin"
    exit 0
  fi
  # Options apply in every project: this project's own settings are not in use.
  printf '{"systemMessage":"%s plugin: this project'"'"'s .claude/settings.local.json has its own UNIFI_%s_* settings, which this plugin version no longer reads, so the %s server uses the plugin options saved from another project, which may name a different controller. They differ from the saved options in %s. To make this project'"'"'s settings the options for every project, ask Claude to run the %s-setup migration with --replace (set-env.sh --target claude --migrate --replace), then %s. To keep the saved options, remove the leftover UNIFI_%s_* keys from that file.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The %s plugin options are set, but this project still holds its own legacy UNIFI_%s_* settings in .claude/settings.local.json, which the plugin no longer reads, so the %s server is using the options saved from another project, which may name a different controller. The connection variables that differ from the saved options are %s. Before using %s tools, tell the user and offer the choice: migrate this project'"'"'s settings with the %s-setup skill (scripts/set-env.sh --target claude --migrate --replace), which makes them the options for every project, or remove the leftover UNIFI_%s_* keys to keep the saved options. Never print those settings or their values."}}\n' \
    "$label" "$upper" "$label" "$differing" "$plugin" "$recover" "$upper" "$plugin" "$upper" "$label" "$differing" "$label" "$plugin" "$upper"
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
