"""Cache-generation behavior for stale-read protection."""

from unifi_core.network.managers.connection_manager import ConnectionManager


def test_prefix_invalidation_does_not_track_an_unseen_cache_key() -> None:
    """Unrelated invalidations must not retain arbitrary key strings forever."""
    manager = ConnectionManager("controller.invalid", "user", "password")
    key = "settings_arbitrary_runtime_section_default"

    manager._invalidate_cache(key)

    assert key not in manager._cache_generations


def test_global_invalidation_does_not_track_an_unguarded_dynamic_cache_key() -> None:
    """Global lifecycle cleanup must not retain ordinary dynamic cache keys."""
    manager = ConnectionManager("controller.invalid", "user", "password")
    key = "settings_arbitrary_runtime_section_default"
    manager._update_cache(key, {"value": True})

    manager._invalidate_cache()

    assert key not in manager._cache_generations
