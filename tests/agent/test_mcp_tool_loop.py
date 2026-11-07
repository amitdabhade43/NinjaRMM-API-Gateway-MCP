import asyncio

import pytest

from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import run_mcp_question


def _tool(name, schema):
    return MCPToolInfo("ninjaone", name, f"ninjaone.{name}", name, schema)


class FakeManager:
    def __init__(self):
        self.tools = [
            _tool("discover_endpoints", {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}),
            _tool("inspect_endpoint", {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": ["endpoint"]}),
            _tool("execute_endpoint", {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": ["endpoint"]}),
        ]
        self.calls = []

    def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "ninjaone.discover_endpoints":
            return {"candidates": [{"endpoint": "GET /v2/devices"}]}
        if name == "ninjaone.inspect_endpoint":
            return {"endpoint": "GET /v2/devices", "parameters": []}
        return {"data": [{"id": 1, "systemName": "2QN-PC"}]}


class FakeLLM:
    def __init__(self, decisions):
        self.decisions = iter(decisions)

    async def complete_json(self, system, user):
        return next(self.decisions)

    async def complete(self, system, user, temperature=0.0):
        return "There is one matching device: 2QN-PC."


def test_bounded_loop_discovers_inspects_and_executes_get():
    manager = FakeManager()
    llm = FakeLLM([
        {"action": "call", "tool": "ninjaone.discover_endpoints", "arguments": {"intent": "list devices"}},
        {"action": "call", "tool": "ninjaone.inspect_endpoint", "arguments": {"endpoint": "GET /v2/devices"}},
        {"action": "call", "tool": "ninjaone.execute_endpoint", "arguments": {"endpoint": "GET /v2/devices"}},
        {"action": "final", "answer": "There is one matching device: 2QN-PC."},
    ])

    answer = asyncio.run(run_mcp_question(llm, manager, "Find devices starting with 2QN"))

    assert answer == "There is one matching device: 2QN-PC."
    assert [call[0] for call in manager.calls] == [
        "ninjaone.discover_endpoints",
        "ninjaone.inspect_endpoint",
        "ninjaone.execute_endpoint",
    ]


def test_loop_normalizes_tool_name_returned_as_action():
    manager = FakeManager()
    llm = FakeLLM([
        {
            "action": "discover_endpoints",
            "tool": "ninjaone.discover_endpoints",
            "arguments": {"intent": "Find devices starting with 2QN"},
        },
        {"action": "final", "answer": "Endpoint discovery completed."},
    ])

    answer = asyncio.run(run_mcp_question(llm, manager, "Find devices starting with 2QN"))

    assert answer == "Endpoint discovery completed."
    assert manager.calls == [
        ("ninjaone.discover_endpoints", {"intent": "Find devices starting with 2QN"})
    ]


def test_loop_maps_choose_endpoint_to_ninjaone_discovery():
    manager = FakeManager()
    llm = FakeLLM([
        {
            "action": "choose_endpoint",
            "description": "Select a suitable OpenAPI endpoint",
            "operation": "list",
        },
        {"action": "final", "answer": "Endpoint discovery completed."},
    ])

    answer = asyncio.run(
        run_mcp_question(llm, manager, "Find devices whose names start with 2QN")
    )

    assert answer == "Endpoint discovery completed."
    assert manager.calls == [
        (
            "ninjaone.discover_endpoints",
            {"intent": "Find devices whose names start with 2QN"},
        )
    ]


def test_loop_blocks_non_get_ninjaone_endpoint():
    manager = FakeManager()
    llm = FakeLLM([
        {"action": "call", "tool": "ninjaone.execute_endpoint", "arguments": {"endpoint": "POST /v2/devices"}},
    ])

    with pytest.raises(PermissionError, match="GET"):
        asyncio.run(run_mcp_question(llm, manager, "Create a device"))
    assert manager.calls == []



def test_loop_normalizes_singular_action_and_fills_missing_intent():
    manager = FakeManager()
    llm = FakeLLM([
        {
            "action": "discover_endpoint",
            "tool": "ninjaone.discover_endpoints",
            "arguments": {},
        },
        {"action": "final", "answer": "Discovery completed."},
    ])

    answer = asyncio.run(
        run_mcp_question(llm, manager, "Show devices beginning with 2QN")
    )

    assert answer == "Discovery completed."
    assert manager.calls == [
        ("ninjaone.discover_endpoints", {"intent": "Show devices beginning with 2QN"})
    ]


def test_loop_routes_get_planning_action_to_discovery_when_tool_is_missing():
    manager = FakeManager()
    llm = FakeLLM([
        {
            "action": "get",
            "endpoint": "GET /v2/inventory",
            "description": "Fetch software inventory",
            "operation": "getInventory",
        },
        {"action": "final", "answer": "Discovery completed."},
    ])

    answer = asyncio.run(
        run_mcp_question(llm, manager, "Find machines with names ending in 001")
    )

    assert answer == "Discovery completed."
    assert manager.calls == [
        ("ninjaone.discover_endpoints", {"intent": "Find machines with names ending in 001"})
    ]


def test_loop_accepts_approved_tool_field_even_when_action_is_not_call():
    manager = FakeManager()
    llm = FakeLLM([
        {
            "action": "discover_endpoint",
            "tool": "ninjaone.discover_endpoints",
            "arguments": {"intent": "list devices"},
        },
        {"action": "final", "answer": "Discovery completed."},
    ])

    answer = asyncio.run(run_mcp_question(llm, manager, "List devices"))

    assert answer == "Discovery completed."
    assert manager.calls == [
        ("ninjaone.discover_endpoints", {"intent": "list devices"})
    ]
