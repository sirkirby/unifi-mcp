#!/bin/sh
# Console-login setup notice only; never print an option, a project setting or a credential.
[ "$1" = innerspace ] || exit 0
if [ -n "${CLAUDE_PLUGIN_OPTION_HOST:-}" ]; then
  exit 0
fi
printf '%s\n' '{"systemMessage":"UniFi InnerSpace needs its console host and login. If setup is needed, use the unifi-innerspace-setup skill and then /reload-plugins or start a new session.","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"The InnerSpace plugin has no console host saved, so its server starts in setup mode, unless the environment that starts Claude Code sets the shared UNIFI_HOST: the server then falls back to it, and to the shared login keys, key by key. InnerSpace uses the console login session only, never an API key. Offer the unifi-innerspace-setup skill, which pins the console certificate before any password is entered; never ask for or print a password. Use /mcp reconnect plugin:unifi-innerspace:unifi-innerspace only if the server is shown as failed."}}'
