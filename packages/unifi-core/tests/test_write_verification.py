"""Exact controller write-outcome classification."""

from unittest.mock import AsyncMock

import pytest
from unifi_core.operation_gate import GateSettings, OperationGate, held_write_remaining_seconds
from unifi_core.write_verification import (
    READBACK_SETTLE_DELAYS_SECONDS,
    READBACK_SETTLE_HOLD_RESERVE_SECONDS,
    SettledReadback,
    failed_write,
    settle_readback,
    verify_write,
)


def test_verify_write_reports_exact_persisted_fields() -> None:
    result = verify_write(
        operation="update",
        requested={"name": "Guest", "enabled": False},
        before={"name": "Old", "enabled": True},
        after={"name": "Guest", "enabled": False},
    )

    assert result.success is True
    assert result.mutation_applied is True
    assert result.persisted_fields == ("enabled", "name")
    assert result.dropped_fields == ()
    assert result.coerced_fields == ()
    assert result.error is None


def test_verify_write_classifies_json_type_changes_as_coercion() -> None:
    for wanted, actual in (
        (True, 1),
        (False, 0),
        (1, 1.0),
        ({"enabled": True}, {"enabled": 1}),
        ([True], [1]),
    ):
        result = verify_write(operation="update", requested={"value": wanted}, after={"value": actual})

        assert result.success is False
        assert result.persisted_fields == ()
        assert result.coerced_fields == ("value",)


def test_verify_write_treats_numeric_string_round_trip_as_persisted() -> None:
    for wanted, actual in (("100", 100), (100, "100"), ("1.5", 1.5)):
        result = verify_write(
            operation="update",
            requested={"vlan": wanted},
            before={"vlan": "40"},
            after={"vlan": actual},
        )

        assert result.success is True, (wanted, actual)
        assert result.persisted_fields == ("vlan",)
        assert result.coerced_fields == ()


def test_verify_write_numeric_string_equivalence_stays_exact() -> None:
    for wanted, actual in (("0100", 100), ("true", True), (True, "True"), ("1", True)):
        result = verify_write(operation="update", requested={"value": wanted}, after={"value": actual})

        assert result.success is False, (wanted, actual)
        assert result.coerced_fields == ("value",)


def test_verify_write_absent_default_true_enabled_is_not_dropped() -> None:
    result = verify_write(
        operation="update",
        requested={"enabled": True},
        before={"_id": "vpn1", "enabled": False},
        after={"_id": "vpn1"},
        absent_value_defaults={"enabled": True},
    )

    assert result.success is True
    assert result.persisted_fields == ("enabled",)
    assert result.dropped_fields == ()


def test_verify_write_absent_default_does_not_mask_real_drop() -> None:
    result = verify_write(
        operation="update",
        requested={"enabled": False},
        before={"_id": "vpn1"},
        after={"_id": "vpn1"},
        absent_value_defaults={"enabled": True},
    )

    assert result.success is False
    assert result.dropped_fields == ("enabled",)


def test_verify_write_reports_already_satisfied_field_as_unchanged() -> None:
    result = verify_write(
        operation="update",
        requested={"enabled": True},
        before={"enabled": True},
        after={"enabled": True},
    )

    assert result.success is True
    assert result.persisted_fields == ()
    assert result.unchanged_fields == ("enabled",)


def test_unchanged_field_does_not_make_dropped_write_partially_successful() -> None:
    result = verify_write(
        operation="update",
        requested={"enabled": True, "guest_policy": True},
        before={"enabled": True, "guest_policy": False},
        after={"enabled": True, "guest_policy": False},
    )

    assert result.success is False
    assert result.partial_success is False
    assert result.persisted_fields == ()
    assert result.unchanged_fields == ("enabled",)
    assert result.dropped_fields == ("guest_policy",)


def test_verify_write_distinguishes_dropped_and_coerced_fields() -> None:
    result = verify_write(
        operation="update",
        requested={"networkconf_id": "new-network", "guest_policy": True, "l2_isolation": True},
        before={"networkconf_id": "old-network", "guest_policy": False, "l2_isolation": False},
        after={"networkconf_id": "new-network", "guest_policy": False, "l2_isolation": "enabled"},
    )

    assert result.success is False
    assert result.partial_success is True
    assert result.persisted_fields == ("networkconf_id",)
    assert result.dropped_fields == ("guest_policy",)
    assert result.coerced_fields == ("l2_isolation",)
    assert "guest_policy" in result.error
    assert "l2_isolation" in result.error


def test_verify_create_flags_missing_as_dropped_and_wrong_value_as_coerced() -> None:
    result = verify_write(
        operation="create",
        requested={"name": "Guest", "purpose": "guest", "enabled": True},
        after={"name": "Guest", "purpose": "corporate"},
    )

    assert result.success is False
    assert result.persisted_fields == ("name",)
    assert result.dropped_fields == ("enabled",)
    assert result.coerced_fields == ("purpose",)


def test_verify_write_skips_unverifiable_secret_fields() -> None:
    result = verify_write(
        operation="update",
        requested={"name": "SSID", "x_passphrase": "new-secret"},
        before={"name": "Old", "x_passphrase": "old-secret"},
        after={"name": "SSID"},
        unverifiable_fields={"x_passphrase"},
    )

    assert result.success is True
    assert result.persisted_fields == ("name",)
    assert result.unverifiable_fields == ("x_passphrase",)


def test_failed_write_distinguishes_no_mutation_from_applied_unknown_result() -> None:
    result = failed_write("Could not re-read resource", mutation_applied=True)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.partial_success is False
    assert result.error == "Could not re-read resource"


class _StepClock:
    """A gate clock that a test moves by hand."""

    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


def _reads(*values):
    remaining = list(values)
    calls = []

    async def read():
        calls.append(None)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return read, calls


@pytest.mark.asyncio
async def test_settle_readback_immediate_match_reads_once_and_never_waits() -> None:
    read, calls = _reads("new")
    sleep = AsyncMock()

    settled = await settle_readback(read, lambda value: value == "new", sleep=sleep)

    assert settled == SettledReadback("new", True, 1, 0.0)
    assert len(calls) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_settle_readback_rereads_a_stale_answer_until_it_matches() -> None:
    read, calls = _reads("old", "old", "new")
    sleep = AsyncMock()

    settled = await settle_readback(read, lambda value: value == "new", sleep=sleep)

    assert settled == SettledReadback("new", True, 3, 0.75)
    assert len(calls) == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5]


@pytest.mark.asyncio
async def test_settle_readback_gives_up_after_its_budget_with_the_last_value() -> None:
    read, calls = _reads("old")
    sleep = AsyncMock()

    settled = await settle_readback(read, lambda value: value == "new", sleep=sleep)

    assert settled.matched is False
    assert settled.value == "old"
    assert settled.reads == len(READBACK_SETTLE_DELAYS_SECONDS) + 1 == len(calls)
    assert settled.waited_seconds == pytest.approx(sum(READBACK_SETTLE_DELAYS_SECONDS))
    assert sum(READBACK_SETTLE_DELAYS_SECONDS) <= 3.0
    assert [call.args[0] for call in sleep.await_args_list] == list(READBACK_SETTLE_DELAYS_SECONDS)


@pytest.mark.asyncio
async def test_settle_readback_propagates_a_failed_read_without_retrying() -> None:
    read = AsyncMock(side_effect=[None, RuntimeError("boom")])
    sleep = AsyncMock()

    with pytest.raises(RuntimeError, match="boom"):
        await settle_readback(read, lambda value: value is not None, sleep=sleep)
    assert read.await_count == 2


@pytest.mark.asyncio
async def test_settle_readback_inside_a_held_write_stays_inside_the_hold_budget() -> None:
    clock = _StepClock()
    gate = OperationGate(GateSettings(hold_budget_seconds=10.0), name="network", clock=clock)
    read, calls = _reads("old")
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.value += seconds

    async with gate.write():
        clock.value += 7.5  # The write has 2.5 s of its hold budget left.
        settled = await settle_readback(read, lambda value: value == "new", sleep=sleep)
        assert held_write_remaining_seconds() >= READBACK_SETTLE_HOLD_RESERVE_SECONDS

    assert waits == [0.25]
    assert settled.matched is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_settle_readback_inside_a_held_write_reads_without_reentering_the_gate() -> None:
    clock = _StepClock()
    gate = OperationGate(GateSettings(hold_budget_seconds=120.0), name="network", clock=clock)
    values = iter(["old", "new"])

    async def read():
        # A write's own read-back passes straight through its held gate.
        async with gate.read():
            return next(values)

    async with gate.write():
        settled = await settle_readback(read, lambda value: value == "new", sleep=clock.sleep)

    assert settled == SettledReadback("new", True, 2, 0.25)
