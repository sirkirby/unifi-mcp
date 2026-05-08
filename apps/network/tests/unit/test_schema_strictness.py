"""CI guard: every wrapper schema must reject unknown keys.

Permissive schemas are the silent-drop class of bug (#135 -> #136 -> #203).
This test asserts ``additionalProperties: false`` is set on every
top-level schema in apps/network's schemas module.

When you add a new schema:
    1. Set ``"additionalProperties": False`` at the top level.
    2. The new schema is automatically covered by this test.
    3. If you cannot make it strict (rare; document the reason inline),
       add it to PERMISSIVE_BY_DESIGN below with a comment pointing at
       the issue/PR explaining why.

Adding a schema to ALLOWED_PERMISSIVE_DURING_SWEEP is a TEMPORARY measure
for the #205 sweep PR only -- entries are removed task-by-task as that PR
progresses. After the sweep PR merges, the list MUST be empty.
"""

from __future__ import annotations

import inspect

from unifi_network_mcp import schemas


# Schemas allowed to remain permissive at sweep-start. Each task in the
# #205 sweep removes one entry. After merge this set MUST be empty.
ALLOWED_PERMISSIVE_DURING_SWEEP: set[str] = set()

# Schemas that are intentionally permissive after the sweep. Each entry
# MUST have a comment justifying why and a reference to the issue/PR
# where the decision was made.
PERMISSIVE_BY_DESIGN: set[str] = set()


def _all_top_level_schemas() -> dict[str, dict]:
    """Return every module-level *_SCHEMA dict declared in schemas.py."""
    return {
        name: value
        for name, value in inspect.getmembers(schemas)
        if name.endswith("_SCHEMA") and isinstance(value, dict)
    }


def test_every_schema_is_either_strict_or_documented():
    """Every wrapper schema must be strict or explicitly opted out.

    Strict = ``additionalProperties: false`` at the top level.
    Opted out = listed in PERMISSIVE_BY_DESIGN (with comment) OR
    ALLOWED_PERMISSIVE_DURING_SWEEP (sweep-only escape hatch).
    """
    schemas_seen = _all_top_level_schemas()
    assert schemas_seen, "Sanity check: at least one *_SCHEMA must exist."

    failures: list[str] = []
    for name, schema in sorted(schemas_seen.items()):
        addl = schema.get("additionalProperties")
        if addl is False:
            continue
        if name in PERMISSIVE_BY_DESIGN:
            continue
        if name in ALLOWED_PERMISSIVE_DURING_SWEEP:
            continue
        failures.append(
            "%s has additionalProperties=%r (must be False, or listed in "
            "PERMISSIVE_BY_DESIGN with justification)." % (name, addl)
        )

    assert not failures, "\n".join(failures)


def test_sweep_escape_hatch_is_eventually_empty():
    """The #205 sweep is complete; the escape hatch is permanently locked.

    If you find yourself wanting to add to ALLOWED_PERMISSIVE_DURING_SWEEP,
    you almost certainly want PERMISSIVE_BY_DESIGN instead -- and you must
    document the justification.
    """
    assert not ALLOWED_PERMISSIVE_DURING_SWEEP, (
        "ALLOWED_PERMISSIVE_DURING_SWEEP must remain empty after #205. "
        "Use PERMISSIVE_BY_DESIGN with justification if a schema must be "
        "permissive."
    )


def test_no_schema_is_explicitly_permissive():
    """Even during the sweep, ``additionalProperties: True`` is never acceptable.

    The default (unset) is permissive but reflects historical drift.
    Explicit ``True`` is a deliberate choice and must be replaced with
    a strict declaration plus a PERMISSIVE_BY_DESIGN entry if the
    permissive behavior is genuinely needed.
    """
    schemas_seen = _all_top_level_schemas()
    explicitly_true = [
        name for name, schema in schemas_seen.items() if schema.get("additionalProperties") is True
    ]
    assert not explicitly_true, (
        "Schemas with explicit additionalProperties=True (use False or omit): %s" % explicitly_true
    )
