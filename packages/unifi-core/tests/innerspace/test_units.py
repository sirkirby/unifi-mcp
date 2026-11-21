"""Unit conversion helpers."""

import math

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.units import from_metres, parse_unit, plan_units_to_metres, to_metres


@pytest.mark.parametrize(
    ("convert", "value", "unit", "expected"),
    [
        (from_metres, 1.0, "imperial", pytest.approx(3.2808)),
        (to_metres, 3.2808, "imperial", pytest.approx(1.0)),
        (from_metres, 2.5, "metric", 2.5),
        (to_metres, 2.5, "metric", 2.5),
        (from_metres, None, "metric", None),
        (to_metres, None, "imperial", None),
    ],
)
def test_length_conversion(convert, value, unit, expected):
    assert convert(value, unit) == expected


def test_plan_units_to_metres():
    assert plan_units_to_metres(300.0, 100.0) == 3.0


@pytest.mark.parametrize("ppm", [0, -5, None, math.nan, math.inf])
def test_plan_units_need_a_usable_scale(ppm):
    assert plan_units_to_metres(10, ppm) is None


@pytest.mark.parametrize("raw", ["furlongs", None, "", 1, "Metric"])
def test_unknown_unit_rejected(raw):
    with pytest.raises(UniFiMalformedResponseError):
        parse_unit(raw)


@pytest.mark.parametrize("raw", ["metric", "imperial"])
def test_known_units_accepted(raw):
    assert parse_unit(raw) == raw
