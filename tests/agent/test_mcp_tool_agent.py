from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import (
    is_read_only_candidate,
    rank_tools,
    validate_tool_arguments,
)


def _tool(server, name, description, schema=None):
    return MCPToolInfo(server, name, f"{server}.{name}", description, schema or {})


def test_tool_shortlist_prefers_relevant_read_only_tools():
    tools = [
        _tool("ninjaone", "discover_endpoints", "Find API endpoints for devices"),
        _tool("filesystem", "read_file", "Read a local file"),
        _tool("ninjaone", "execute_endpoint", "Execute a GET endpoint"),
    ]

    ranked = rank_tools("find NinjaOne device endpoints", tools)

    assert ranked
    assert ranked[0].qualified_name == "ninjaone.discover_endpoints"


def test_write_tools_are_not_read_only_candidates():
    assert not is_read_only_candidate(_tool("filesystem", "write_file", "Write a file"))
    assert not is_read_only_candidate(_tool("ninjaone", "execute_raw_request", "Run raw API request"))
    assert is_read_only_candidate(_tool("ninjaone", "inspect_endpoint", "Inspect API endpoint"))


def test_tool_arguments_require_schema_fields_and_reject_unknown_fields():
    tool = _tool("demo", "get_item", "Get item", {
        "type": "object",
        "properties": {"item_id": {"type": "string"}},
        "required": ["item_id"],
    })

    assert validate_tool_arguments(tool, {"item_id": "123"}) == {"item_id": "123"}

    try:
        validate_tool_arguments(tool, {})
    except ValueError as exc:
        assert "Missing required" in str(exc)
    else:
        raise AssertionError("Missing required argument was accepted")

    try:
        validate_tool_arguments(tool, {"item_id": "123", "admin": True})
    except ValueError as exc:
        assert "Unsupported tool argument" in str(exc)
    else:
        raise AssertionError("Unknown argument was accepted")
