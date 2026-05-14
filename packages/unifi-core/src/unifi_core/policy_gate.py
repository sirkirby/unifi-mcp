"""Policy gate checker and permission mode resolver.

Policy gates are hard boundaries that disable specific actions via env vars.
Three-level hierarchy (most specific wins):
    UNIFI_POLICY_<ACTION>                              - global
    UNIFI_POLICY_<SERVER>_<ACTION>                     - per-server
    UNIFI_POLICY_<SERVER>_<CATEGORY>_<ACTION>           - per-category

Permission mode controls mutation handling:
    UNIFI_TOOL_PERMISSION_MODE=confirm|bypass           - global
    UNIFI_<SERVER>_TOOL_PERMISSION_MODE=confirm|bypass  - per-server
"""

import logging
import os

logger = logging.getLogger(__name__)

VALID_PERMISSION_MODES = ("confirm", "bypass")
_TRUTHY = frozenset(("true", "1", "yes", "on"))
_FALSY = frozenset(("false", "0", "no", "off"))


class PolicyGateChecker:
    """Check policy gates via 3-level env var hierarchy."""

    def __init__(
        self,
        server_prefix: str,
        category_map: dict[str, str] | None = None,
    ):
        self.server_prefix = server_prefix.upper()
        self.category_map = category_map or {}

    def _resolve_category(self, category: str) -> str:
        """Resolve category shorthand to config key."""
        return self.category_map.get(category, category)

    def check(self, category: str, action: str) -> bool:
        """Check if an action is allowed by policy gates.

        Returns True if allowed, False if denied.
        If no gate is set, the action is allowed.
        Read actions always return True (not gateable).
        """
        if action.lower() == "read":
            return True

        config_key = self._resolve_category(category).upper()
        action_upper = action.upper()

        # Most specific wins: category > server > global
        env_vars = [
            f"UNIFI_POLICY_{self.server_prefix}_{config_key}_{action_upper}",
            f"UNIFI_POLICY_{self.server_prefix}_{action_upper}",
            f"UNIFI_POLICY_{action_upper}",
        ]

        for var in env_vars:
            value = os.environ.get(var)
            if value is not None:
                normalized = value.strip().lower()
                result = normalized in _TRUTHY
                if not result and normalized not in _FALSY:
                    logger.warning("[policy] Unrecognized value for %s=%s, treating as denied", var, value)
                    result = False
                logger.info("[policy] %s=%s -> %s", var, value, "allowed" if result else "denied")
                return result

        # 4. Backwards compat: old UNIFI_PERMISSIONS_ format
        old_var = f"UNIFI_PERMISSIONS_{config_key}_{action_upper}"
        old_value = os.environ.get(old_var)
        if old_value is not None:
            normalized = old_value.strip().lower()
            result = normalized in _TRUTHY
            return result

        return True  # No gate set = allowed

    def denial_message(self, category: str, action: str) -> str:
        """Build a user-friendly denial message with enable hint."""
        config_key = self._resolve_category(category).upper()
        action_upper = action.upper()
        enable_var = f"UNIFI_POLICY_{self.server_prefix}_{config_key}_{action_upper}"
        return f"{action.capitalize()} is disabled by policy for {category}. Set {enable_var}=true to enable."


def resolve_permission_mode(server_prefix: str) -> str:
    """Resolve the permission mode for a server.

    Priority: server-specific > global > UNIFI_AUTO_CONFIRM compat > default.
    """
    prefix_upper = server_prefix.upper()

    # 1. Server-specific mode
    server_var = f"UNIFI_{prefix_upper}_TOOL_PERMISSION_MODE"
    server_val = os.environ.get(server_var)
    if server_val and server_val.strip().lower() in VALID_PERMISSION_MODES:
        return server_val.strip().lower()

    # 2. Global mode
    global_val = os.environ.get("UNIFI_TOOL_PERMISSION_MODE")
    if global_val and global_val.strip().lower() in VALID_PERMISSION_MODES:
        return global_val.strip().lower()

    # 3. Backwards compat: UNIFI_AUTO_CONFIRM=true -> bypass
    auto_confirm = os.environ.get("UNIFI_AUTO_CONFIRM", "").strip().lower()
    if auto_confirm in _TRUTHY:
        logger.warning("[permissions] UNIFI_AUTO_CONFIRM is deprecated. Use UNIFI_TOOL_PERMISSION_MODE=bypass instead.")
        return "bypass"

    # 4. Default
    return "confirm"


def check_deprecated_env_vars(server_prefix: str, logger) -> None:
    """Log deprecation warnings for old-format permission env vars at startup."""
    old_prefix = "UNIFI_PERMISSIONS_"
    prefix_upper = server_prefix.upper()
    for key, value in os.environ.items():
        if key.startswith(old_prefix):
            category_action = key[len(old_prefix) :]
            new_key = f"UNIFI_POLICY_{prefix_upper}_{category_action}"
            logger.warning(
                "[permissions] Deprecated env var %s=%s detected. "
                "Use %s=%s instead. Old format will be removed in a future release.",
                key,
                value,
                new_key,
                value,
            )
    # Also check UNIFI_AUTO_CONFIRM
    if os.environ.get("UNIFI_AUTO_CONFIRM"):
        logger.warning("[permissions] UNIFI_AUTO_CONFIRM is deprecated. Use UNIFI_TOOL_PERMISSION_MODE=bypass instead.")
