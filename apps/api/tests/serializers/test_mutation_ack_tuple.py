"""Mutation-ack (ok, error) tuple unwrapping in Serializer.serialize_action.

Fetch-merge-put update managers (update_network / update_wlan /
update_gateway_settings) return a ``(bool, Optional[str])`` ack tuple. The action
path must surface it as a structured ``{"success", "error"}`` envelope rather than
stringify it (which previously reported every result as success).
"""

import pytest
from unifi_api.serializers._base import RenderKind, Serializer, _is_ack_tuple


class _AckSerializer(Serializer):
    kind = RenderKind.DETAIL

    @staticmethod
    def serialize(obj) -> dict:
        # Mirrors the real mutation-ack serializers' fallback for non-tuple input.
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        return {"result": str(obj)}


def test_is_ack_tuple_true_cases():
    assert _is_ack_tuple((True, None))
    assert _is_ack_tuple((False, "boom"))


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        {"_id": "x"},
        ("a", "b"),  # first element not a bool
        (True, 5),  # second element not str/None
        (True, None, "extra"),  # wrong arity
        [True, None],  # list, not tuple
    ],
)
def test_is_ack_tuple_false_cases(value):
    assert not _is_ack_tuple(value)


def test_serialize_action_unwraps_success_tuple():
    out = _AckSerializer().serialize_action((True, None), tool_name="unifi_update_network")
    assert out == {"success": True}


def test_serialize_action_unwraps_failure_tuple():
    out = _AckSerializer().serialize_action((False, "did not persist: x"), tool_name="unifi_update_network")
    assert out == {"success": False, "error": "did not persist: x"}


def test_serialize_action_bool_result_unchanged():
    # Non-tuple results still flow through the kind-based path (regression guard).
    out = _AckSerializer().serialize_action(True, tool_name="unifi_update_network")
    assert out["success"] is True
    assert out["data"] == {"success": True}
    assert out["render_hint"]["kind"] == "detail"
