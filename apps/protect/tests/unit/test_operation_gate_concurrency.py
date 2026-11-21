"""Through the real tool dispatch against a fake controller, the gate orders and caps Protect calls.

A fresh interpreter imports the app's main module first, so its real wiring
(operation gate, connection wait, policy check) registers the tool module; the
controller is faked at the manager boundary. See testsupport/gate_concurrency_driver.py.
"""

from __future__ import annotations

import pytest
from gate_concurrency_driver import READ_CAP, run_in_subprocess

PRODUCT = "protect"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return run_in_subprocess(PRODUCT, cwd=str(tmp_path_factory.mktemp("gate")))


def test_concurrent_confirmed_writes_never_overlap_and_run_in_submission_order(report):
    writes = report["direct_writes"]
    assert writes["overlap"] is False
    assert writes["order"] == writes["expected"]
    assert all(writes["success"])


def test_reads_run_concurrently_up_to_the_cap(report):
    assert report["reads"]["peak"] == READ_CAP
    assert all(report["reads"]["success"])


def test_a_batch_of_writes_runs_in_submission_order(report):
    batch = report["batch"]
    assert batch["order"] == batch["expected"]
    assert batch["statuses"] == ["done"] * len(batch["expected"])
    assert batch["overlap"] is False


def test_batch_cancel_withdraws_a_queued_write_and_refuses_a_running_one(report):
    cancel = report["cancel"]
    assert cancel["cancelled"] is True
    assert cancel["running_refused"] is True
    assert cancel["order"] == cancel["expected"]
    assert cancel["statuses"] == ["done", "cancelled", "done"]
