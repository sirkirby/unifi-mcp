"""Exact controller write-outcome classification."""

from unifi_core.write_verification import failed_write, verify_write


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
