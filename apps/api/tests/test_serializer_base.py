"""Serializer base + decorator tests."""

import pytest
from unifi_api.serializers._base import (
    RenderKind,
    Serializer,
    SerializerContractError,
    register_serializer,
)


def test_render_kind_values() -> None:
    assert RenderKind.LIST.value == "list"
    assert RenderKind.DETAIL.value == "detail"
    assert RenderKind.DIFF.value == "diff"
    assert RenderKind.TIMESERIES.value == "timeseries"
    assert RenderKind.EVENT_LOG.value == "event_log"
    assert RenderKind.EMPTY.value == "empty"


def test_register_serializer_with_bare_list_form() -> None:
    @register_serializer(tools=["test_tool_a", "test_tool_b"], resources=[("test_product", "test_resource")])
    class TestSer(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return {"x": obj}

    # Decorator returns the class unchanged
    assert TestSer.kind == RenderKind.LIST


def test_register_serializer_with_dict_form_per_tool_kind() -> None:
    @register_serializer(
        tools={
            "tool_x": {"kind": RenderKind.LIST},
            "tool_y": {"kind": RenderKind.DETAIL},
        },
    )
    class MultiSer(Serializer):
        @staticmethod
        def serialize(obj):
            return obj


def test_serialize_action_list_kind() -> None:
    @register_serializer(tools=["t_list"])
    class ListSer(Serializer):
        kind = RenderKind.LIST
        primary_key = "id"

        @staticmethod
        def serialize(obj):
            return {"id": obj}

    inst = ListSer()
    out = inst.serialize_action([1, 2, 3], tool_name="t_list")
    assert out == {
        "success": True,
        "data": [{"id": 1}, {"id": 2}, {"id": 3}],
        "render_hint": {"kind": "list", "primary_key": "id"},
    }


def test_serialize_action_detail_kind() -> None:
    @register_serializer(tools=["t_detail"])
    class DetSer(Serializer):
        kind = RenderKind.DETAIL

        @staticmethod
        def serialize(obj):
            return {"name": obj}

    inst = DetSer()
    out = inst.serialize_action("foo", tool_name="t_detail")
    assert out == {
        "success": True,
        "data": {"name": "foo"},
        "render_hint": {"kind": "detail"},
    }


def test_serialize_action_detail_redacts_sensitive_fields() -> None:
    from unifi_core.redaction import REDACTED

    @register_serializer(tools=["t_secret"])
    class SecretSer(Serializer):
        kind = RenderKind.DETAIL

        @staticmethod
        def serialize(obj):
            return {"id": "1", "x_passphrase": obj}

    out = SecretSer().serialize_action("wifi-secret", tool_name="t_secret")

    assert out["data"]["x_passphrase"] == REDACTED


def test_serialize_action_list_redacts_sensitive_fields() -> None:
    from unifi_core.redaction import REDACTED

    @register_serializer(tools=["t_secret_list"])
    class SecretListSer(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return {"id": obj, "token": "tok"}

    out = SecretListSer().serialize_action(["a"], tool_name="t_secret_list")

    assert out["data"][0]["token"] == REDACTED


def test_serialize_action_redact_sensitive_false_opts_out_of_redaction() -> None:
    @register_serializer(tools=["t_secret_opt_out"])
    class OptOutSer(Serializer):
        kind = RenderKind.DETAIL

        @staticmethod
        def serialize(obj):
            return {"id": "1", "x_passphrase": obj}

    out = OptOutSer().serialize_action("wifi-secret", tool_name="t_secret_opt_out", redact_sensitive=False)

    assert out["data"]["x_passphrase"] == "wifi-secret"


def test_serialize_action_empty_kind() -> None:
    @register_serializer(tools=["t_empty"])
    class EmpSer(Serializer):
        kind = RenderKind.EMPTY

        @staticmethod
        def serialize(obj):
            return obj

    inst = EmpSer()
    out = inst.serialize_action(None, tool_name="t_empty")
    assert out == {"success": True, "render_hint": {"kind": "empty"}}


def test_contract_error_when_list_kind_gets_non_list() -> None:
    @register_serializer(tools=["t_mismatch"])
    class MisSer(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return obj

    inst = MisSer()
    with pytest.raises(SerializerContractError, match="declared kind=list"):
        inst.serialize_action({"single": "object"}, tool_name="t_mismatch")
