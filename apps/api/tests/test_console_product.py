"""The read and error plumbing InnerSpace and UniFi Drive share as console products."""

from __future__ import annotations

import pytest
from unifi_api.graphql.types._projection import ConsoleProjection
from unifi_api.services.console_product import map_error
from unifi_api.services.drive import DRIVE, DriveAPIError
from unifi_api.services.innerspace import INNERSPACE, InnerSpaceAPIError
from unifi_api.services.managers import ControllerInitializationFailed
from unifi_core.exceptions import (
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.innerspace.managers.connection_manager import InnerSpaceHttpError
from unifi_core.operation_gate import BUSY_RETRY_AFTER_SECONDS

PRODUCTS = [pytest.param(DRIVE, id="drive"), pytest.param(INNERSPACE, id="innerspace")]


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize(
    ("error", "status", "suffix", "code"),
    [
        (UniFiValidationError("bad"), 422, "invalid_{}_request", "BAD_REQUEST"),
        (UniFiNotFoundError("share", "s-1"), 404, "{}_not_found", "NOT_FOUND"),
        (UniFiPermissionError("no"), 403, "{}_forbidden", "UPSTREAM_FORBIDDEN"),
        (UniFiRateLimitError("slow down"), 429, "{}_rate_limited", "RATE_LIMITED"),
        (UniFiConnectionError("timed out"), 502, "{}_upstream_error", "UPSTREAM_ERROR"),
        (RuntimeError("boom"), 500, "{}_internal_error", "INTERNAL"),
    ],
)
def test_each_product_answers_with_its_own_kinds(product, error, status, suffix, code):
    mapped = map_error(product, error, "read the thing")

    assert isinstance(mapped, product.error)
    assert (mapped.status, mapped.kind, mapped.graphql_code) == (status, suffix.format(product.key), code)
    assert mapped.message.startswith("Failed to read the thing: ")
    assert mapped.retry_after is None


@pytest.mark.parametrize(("product", "label"), [(DRIVE, "UniFi Drive"), (INNERSPACE, "InnerSpace")])
def test_a_connection_that_never_opened_names_the_product(product, label):
    mapped = map_error(product, ConnectionError("refused 192.0.2.1:443"), "read the thing")

    assert (mapped.status, mapped.kind) == (502, f"{product.key}_upstream_error")
    assert mapped.message == f"Failed to read the thing: could not connect to {label}."


@pytest.mark.parametrize("product", PRODUCTS)
def test_a_factory_failure_names_the_failed_action_once(product):
    reason = "the controller has no username and password."
    error = ControllerInitializationFailed(f"Failed to initialize {product.key} controller connection: {reason}")

    assert map_error(product, error, "read the thing").message == f"Failed to read the thing: {reason}"


def test_only_innerspace_answers_a_restarting_application_as_retryable():
    restarting = InnerSpaceHttpError("InnerSpace answered HTTP 503.", status=503)

    innerspace = map_error(INNERSPACE, restarting, "read the thing")
    drive = map_error(DRIVE, restarting, "read the thing")

    assert (innerspace.status, innerspace.kind, innerspace.retry_after) == (
        503,
        "innerspace_unavailable",
        BUSY_RETRY_AFTER_SECONDS,
    )
    assert innerspace.graphql_code == "UPSTREAM_ERROR"
    assert (drive.status, drive.kind, drive.retry_after) == (502, "drive_upstream_error", None)


@pytest.mark.parametrize("error", [DriveAPIError(404, "drive_not_found", "x"), InnerSpaceAPIError(404, "k", "x")])
def test_an_already_mapped_error_passes_through(error):
    assert map_error(DRIVE, error, "read the thing") is error


def test_a_kind_from_another_product_is_not_given_its_code():
    assert DriveAPIError(404, "innerspace_not_found", "x").graphql_code == "INTERNAL"


@pytest.mark.parametrize("label", ["UniFi Drive", "InnerSpace"])
def test_a_console_projection_refuses_a_reply_that_is_not_an_object(label):
    projection = type("Thing", (ConsoleProjection,), {"_product_label": label})

    with pytest.raises(UniFiMalformedResponseError, match=f"^{label} returned an unreadable result$"):
        projection.from_manager_output(["not", "an", "object"])
