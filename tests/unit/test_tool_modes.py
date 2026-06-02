import asyncio

import pytest

import server


def _run(coro):
    return asyncio.run(coro)


def test_compact_mode_exposes_only_capability_tools():
    async def scenario():
        try:
            mode = await server.configure_mcp_tool_mode("compact")
            tools = await server.mcp.list_tools()

            assert mode == "compact"
            assert {tool.name for tool in tools} == {
                "abap_list_capabilities",
                "abap_get_capability_spec",
                "abap_call_capability",
                "abap_skills_install",
            }
            assert "login" in server.CAPABILITY_TOOLS
            assert "sap_systems_list" in server.CAPABILITY_TOOLS
            assert "internals_object_lock_probe" in server.CAPABILITY_TOOLS
            assert "workflow_start" in server.CAPABILITY_TOOLS
            assert "workflow_log" in server.CAPABILITY_TOOLS
            assert "classrun_run" in server.CAPABILITY_TOOLS
            assert "abap_skills_install" not in server.CAPABILITY_TOOLS
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_capability_list_is_lightweight_and_categorized():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_list_capabilities",
                {"query": "sap systems"},
            )

            capabilities = result.structured_content["capabilities"]
            assert capabilities == [{
                "name": "sap_systems_list",
                "category": "sap.systems",
                "description": "List the SAP systems configured in the MCP server, including their ids, names, and environment types.",
            }]
            assert "inputSchema" not in capabilities[0]
            assert "outputSchema" not in capabilities[0]
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_capability_spec_returns_full_schema_on_demand():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_get_capability_spec",
                {"name": "login"},
            )

            spec = result.structured_content
            assert spec["name"] == "login"
            assert spec["category"] == "login"
            assert spec["inputSchema"]["required"] == ["systemId"]
            assert "systemId" in spec["inputSchema"]["properties"]
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_capability_spec_includes_internals_object_lock_probe():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_get_capability_spec",
                {"name": "internals_object_lock_probe"},
            )

            spec = result.structured_content
            assert spec["name"] == "internals_object_lock_probe"
            assert spec["category"] == "internals"
            assert set(spec["inputSchema"]["required"]) == {"systemId", "objectUri"}
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_capability_spec_includes_workflow_tools():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_get_capability_spec",
                {"name": "workflow_start"},
            )

            spec = result.structured_content
            assert spec["name"] == "workflow_start"
            assert spec["category"] == "workflow"
            assert set(spec["inputSchema"]["required"]) == {"workflow", "projectPath", "task"}
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_capability_spec_includes_classrun_run():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_get_capability_spec",
                {"name": "classrun_run"},
            )

            spec = result.structured_content
            assert spec["name"] == "classrun_run"
            assert spec["category"] == "classrun"
            assert set(spec["inputSchema"]["required"]) == {"systemId", "className"}
            assert "ADT classrun endpoint" in spec["description"]
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_compact_call_capability_delegates_to_original_tool():
    async def scenario():
        try:
            await server.configure_mcp_tool_mode("compact")

            result = await server.mcp.call_tool(
                "abap_call_capability",
                {"name": "sap_systems_list", "arguments": {}},
            )

            assert result.structured_content["result"] is True
            assert result.structured_content["data"]["totalCount"] >= 0
        finally:
            await server.configure_mcp_tool_mode("full")

    _run(scenario())


def test_full_mode_restores_original_public_tools():
    async def scenario():
        await server.configure_mcp_tool_mode("compact")
        mode = await server.configure_mcp_tool_mode("full")
        tools = await server.mcp.list_tools()

        assert mode == "full"
        assert len(tools) > 100
        assert "login" in {tool.name for tool in tools}
        assert "abap_skills_install" in {tool.name for tool in tools}
        assert "workflow_start" in {tool.name for tool in tools}
        assert "workflow_log" in {tool.name for tool in tools}
        assert not ({tool.name for tool in tools} & server.COMPACT_DISPATCHER_TOOL_NAMES)

    _run(scenario())


def test_invalid_tool_mode_is_rejected():
    with pytest.raises(ValueError, match="ABAP_MCP_TOOL_MODE"):
        server._normalize_tool_mode("wide")
