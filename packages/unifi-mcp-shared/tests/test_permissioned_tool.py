"""Tests for the shared permissioned_tool factory."""

import asyncio
import inspect
import logging
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from unifi_mcp_shared.output_schema import (
    UniFiToolResponse,
    get_unifi_tool_response_output_schema,
)
from unifi_mcp_shared.permissioned_tool import _infer_input_schema, create_permissioned_tool


@pytest.fixture
def mock_deps():
    """Create mock dependencies for the factory."""
    registered_tools = {}
    mcp_registered = {}
    mcp_tool_kwargs = {}

    def fake_register(
        name,
        description="",
        input_schema=None,
        output_schema=None,
        auth_method="local_only",
        permission_category=None,
        permission_action=None,
    ):
        registered_tools[name] = {
            "description": description,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "auth_method": auth_method,
            "permission_category": permission_category,
            "permission_action": permission_action,
        }

    def fake_tool_decorator(*args, **kwargs):
        """Decorator that captures the wrapped function for testing."""

        def decorator(func):
            name = kwargs.get("name") or (args[0] if args else getattr(func, "__name__", "<unknown>"))
            mcp_registered[name] = func
            mcp_tool_kwargs[name] = kwargs.copy()
            return func

        return decorator

    checker = MagicMock()
    checker.check = MagicMock(return_value=True)
    checker.denial_message = MagicMock(
        return_value="Delete is disabled by policy for cat. Set UNIFI_POLICY_NETWORK_CAT_DELETE=true to enable."
    )

    return {
        "original_tool_decorator": fake_tool_decorator,
        "policy_gate_checker": checker,
        "server_prefix": "NETWORK",
        "register_tool_fn": fake_register,
        "diagnostics_enabled_fn": lambda: False,
        "wrap_tool_fn": lambda func, name: func,
        "logger": logging.getLogger("test"),
        "registered_tools": registered_tools,
        "mcp_registered": mcp_registered,
        "mcp_tool_kwargs": mcp_tool_kwargs,
    }


def _create_pt(mock_deps):
    """Helper to create a permissioned_tool from mock deps."""
    return create_permissioned_tool(
        original_tool_decorator=mock_deps["original_tool_decorator"],
        policy_gate_checker=mock_deps["policy_gate_checker"],
        server_prefix=mock_deps["server_prefix"],
        register_tool_fn=mock_deps["register_tool_fn"],
        diagnostics_enabled_fn=mock_deps["diagnostics_enabled_fn"],
        wrap_tool_fn=mock_deps["wrap_tool_fn"],
        logger=mock_deps["logger"],
    )


class TestCreatePermissionedTool:
    """Tests for create_permissioned_tool factory."""

    def test_registers_tool_without_permissions(self, mock_deps):
        pt = _create_pt(mock_deps)

        @pt(name="test_tool", description="A test")
        async def test_tool():
            return {"success": True}

        assert "test_tool" in mock_deps["registered_tools"]
        # Also registered with MCP (fast path)
        assert "test_tool" in mock_deps["mcp_registered"]

    def test_registers_tool_with_permission_allowed(self, mock_deps):
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        @pt(name="perm_tool", description="test", permission_category="cat", permission_action="read")
        async def perm_tool():
            return {"success": True}

        assert "perm_tool" in mock_deps["registered_tools"]
        # Always registered with MCP now
        assert "perm_tool" in mock_deps["mcp_registered"]

    def test_always_registers_with_mcp(self, mock_deps):
        """Even when policy gate would deny, tool IS registered with MCP."""
        mock_deps["policy_gate_checker"].check.return_value = False
        pt = _create_pt(mock_deps)

        @pt(name="denied_tool", description="test", permission_category="cat", permission_action="delete")
        async def denied_tool():
            return {"success": True}

        # Registered in tool index
        assert "denied_tool" in mock_deps["registered_tools"]
        assert mock_deps["registered_tools"]["denied_tool"]["permission_category"] == "cat"
        assert mock_deps["registered_tools"]["denied_tool"]["permission_action"] == "delete"
        # NOW also registered with MCP (the key change from old behavior)
        assert "denied_tool" in mock_deps["mcp_registered"]

    def test_passes_permission_metadata_to_register(self, mock_deps):
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        @pt(name="perm_tool", description="test", permission_category="networks", permission_action="update")
        async def perm_tool():
            return {"success": True}

        assert mock_deps["registered_tools"]["perm_tool"]["permission_category"] == "networks"
        assert mock_deps["registered_tools"]["perm_tool"]["permission_action"] == "update"

    def test_registers_default_output_schema_for_standard_tools(self, mock_deps):
        pt = _create_pt(mock_deps)

        @pt(name="schema_tool", description="test")
        async def schema_tool():
            return {"success": True, "data": {"id": "abc"}}

        schema = mock_deps["registered_tools"]["schema_tool"]["output_schema"]
        assert schema == get_unifi_tool_response_output_schema()
        assert set(schema["properties"]) >= {"success", "data", "error", "requires_confirmation", "preview"}

    def test_preserves_explicit_output_schema_for_tool_index_metadata(self, mock_deps):
        pt = _create_pt(mock_deps)
        custom_schema = {
            "type": "object",
            "properties": {
                "loaded": {"type": "array", "items": {"type": "string"}},
                "errors": {"type": "array"},
            },
        }

        @pt(name="custom_schema_tool", description="test", output_schema=custom_schema)
        async def custom_schema_tool():
            return {"loaded": ["a"], "errors": []}

        assert mock_deps["registered_tools"]["custom_schema_tool"]["output_schema"] == custom_schema

    def test_mcp_registration_enables_structured_output_with_response_model(self, mock_deps):
        pt = _create_pt(mock_deps)

        @pt(name="structured_schema_tool", description="test")
        async def structured_schema_tool():
            return {"success": True}

        assert mock_deps["mcp_tool_kwargs"]["structured_schema_tool"]["structured_output"] is True
        signature = inspect.signature(mock_deps["mcp_registered"]["structured_schema_tool"])
        assert signature.return_annotation is UniFiToolResponse

    @pytest.mark.asyncio
    async def test_fastmcp_exposes_output_schema_and_structured_content(self, mock_deps):
        server = FastMCP("test")
        mock_deps = {
            **mock_deps,
            "original_tool_decorator": server.tool,
        }
        pt = _create_pt(mock_deps)

        @pt(name="fastmcp_schema_tool", description="test")
        async def fastmcp_schema_tool():
            return {"success": True, "data": {"id": "abc"}}

        tools = await server.list_tools()
        tool = next(t for t in tools if t.name == "fastmcp_schema_tool")
        assert tool.outputSchema == get_unifi_tool_response_output_schema()

        content, structured_content = await server.call_tool("fastmcp_schema_tool", {})
        assert content[0].type == "text"
        assert '"success": true' in content[0].text
        assert structured_content == {"success": True, "data": {"id": "abc"}}

    def test_uses_function_name_when_no_name_given(self, mock_deps):
        pt = _create_pt(mock_deps)

        @pt(description="test")
        async def my_auto_named_tool():
            return {}

        assert "my_auto_named_tool" in mock_deps["registered_tools"]

    def test_policy_gate_denial_at_call_time(self, mock_deps):
        """When policy gate denies, the wrapped function returns error dict."""
        mock_deps["policy_gate_checker"].check.return_value = False
        mock_deps[
            "policy_gate_checker"
        ].denial_message.return_value = (
            "Delete is disabled by policy for cat. Set UNIFI_POLICY_NETWORK_CAT_DELETE=true to enable."
        )
        pt = _create_pt(mock_deps)

        @pt(name="denied_tool", description="test", permission_category="cat", permission_action="delete")
        async def denied_tool():
            return {"success": True}

        # Call the wrapped function — should get denial
        result = asyncio.run(mock_deps["mcp_registered"]["denied_tool"]())
        assert result["success"] is False
        assert "disabled by policy" in result["error"]

    def test_bypass_mode_injects_confirm_true(self, mock_deps):
        """In bypass mode, confirm=True is injected for mutation tools."""
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        received_kwargs = {}

        @pt(name="mut_tool", description="test", permission_category="cat", permission_action="create")
        async def mut_tool(name: str, confirm: bool = False):
            received_kwargs.update({"confirm": confirm, "name": name})
            return {"success": True}

        with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value="bypass"):
            result = asyncio.run(mock_deps["mcp_registered"]["mut_tool"](name="test"))

        assert result == {"success": True}
        assert received_kwargs["confirm"] is True

    def test_bypass_mode_respects_explicit_confirm_false(self, mock_deps):
        """In bypass mode, explicit confirm=False from caller is NOT overridden."""
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        received_kwargs = {}

        @pt(name="mut_tool", description="test", permission_category="cat", permission_action="create")
        async def mut_tool(name: str, confirm: bool = False):
            received_kwargs.update({"confirm": confirm, "name": name})
            return {"success": True}

        with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value="bypass"):
            result = asyncio.run(mock_deps["mcp_registered"]["mut_tool"](name="test", confirm=False))

        assert result == {"success": True}
        assert received_kwargs["confirm"] is False  # Explicit False preserved

    def test_confirm_mode_does_not_inject(self, mock_deps):
        """In confirm mode, confirm is NOT modified."""
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        received_kwargs = {}

        @pt(name="mut_tool", description="test", permission_category="cat", permission_action="create")
        async def mut_tool(name: str, confirm: bool = False):
            received_kwargs.update({"confirm": confirm, "name": name})
            return {"success": True}

        with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value="confirm"):
            result = asyncio.run(mock_deps["mcp_registered"]["mut_tool"](name="test"))

        assert result == {"success": True}
        assert received_kwargs["confirm"] is False

    def test_read_action_skips_bypass_injection(self, mock_deps):
        """Read tools don't get confirm injected even in bypass mode."""
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        received_kwargs = {}

        @pt(name="read_tool", description="test", permission_category="cat", permission_action="read")
        async def read_tool(confirm: bool = False):
            received_kwargs["confirm"] = confirm
            return {"success": True}

        with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value="bypass"):
            result = asyncio.run(mock_deps["mcp_registered"]["read_tool"]())

        assert result == {"success": True}
        assert received_kwargs["confirm"] is False

    def test_fast_path_no_wrapper_for_unpermissioned_tools(self, mock_deps):
        """Tools without permission_category/action go through fast path (no wrapper)."""
        pt = _create_pt(mock_deps)

        @pt(name="simple_tool", description="test")
        async def simple_tool():
            return {"success": True}

        # Fast path: function registered directly (no policy gate wrapper)
        # policy_gate_checker should NOT have been called
        mock_deps["policy_gate_checker"].check.assert_not_called()

    def test_diagnostics_wrapping_applied(self, mock_deps):
        """When diagnostics enabled, wrap_tool_fn is applied to gated function."""
        mock_deps["diagnostics_enabled_fn"] = lambda: True
        wrap_calls = []

        def tracking_wrap(func, name):
            wrap_calls.append(name)
            return func

        mock_deps["wrap_tool_fn"] = tracking_wrap
        mock_deps["policy_gate_checker"].check.return_value = True
        pt = _create_pt(mock_deps)

        @pt(name="diag_tool", description="test", permission_category="cat", permission_action="read")
        async def diag_tool():
            return {"success": True}

        assert "diag_tool" in wrap_calls

    def test_diagnostics_wrapping_applied_fast_path(self, mock_deps):
        """When diagnostics enabled, wrap_tool_fn is also applied on the fast path (no permissions)."""
        mock_deps["diagnostics_enabled_fn"] = lambda: True
        wrap_calls = []

        def tracking_wrap(func, name):
            wrap_calls.append(name)
            return func

        mock_deps["wrap_tool_fn"] = tracking_wrap
        pt = _create_pt(mock_deps)

        @pt(name="simple_tool", description="test")
        async def simple_tool():
            return {"success": True}

        assert "simple_tool" in wrap_calls


class TestInferInputSchema:
    """Tests for _infer_input_schema."""

    def test_infers_string_param(self):
        async def tool(name: str):
            pass

        schema = _infer_input_schema(tool, "tool", logging.getLogger("test"))
        assert schema["properties"]["name"]["type"] == "string"
        assert "name" in schema.get("required", [])

    def test_infers_int_param(self):
        async def tool(count: int):
            pass

        schema = _infer_input_schema(tool, "tool", logging.getLogger("test"))
        assert schema["properties"]["count"]["type"] == "integer"

    def test_infers_bool_param(self):
        async def tool(flag: bool = False):
            pass

        schema = _infer_input_schema(tool, "tool", logging.getLogger("test"))
        assert schema["properties"]["flag"]["type"] == "boolean"
        assert "flag" not in schema.get("required", [])

    def test_infers_optional_param(self):
        async def tool(name: str | None = None):
            pass

        schema = _infer_input_schema(tool, "tool", logging.getLogger("test"))
        assert schema["properties"]["name"]["type"] == "string"
        assert "name" not in schema.get("required", [])

    def test_skips_self_and_cls(self):
        async def tool(self, name: str):
            pass

        schema = _infer_input_schema(tool, "tool", logging.getLogger("test"))
        assert "self" not in schema["properties"]
