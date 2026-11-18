"""Tool diagnostics, re-exported from the shared package."""

from unifi_core.diagnostics import diagnostics_enabled, init_diagnostics, wrap_tool


def _get_config():
    from unifi_innerspace_mcp.runtime import config

    return config


init_diagnostics(
    config_provider=_get_config,
    logger_name="unifi-innerspace-mcp.diagnostics",
)

__all__ = ["diagnostics_enabled", "init_diagnostics", "wrap_tool"]
