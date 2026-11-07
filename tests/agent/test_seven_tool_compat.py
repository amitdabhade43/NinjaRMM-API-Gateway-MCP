import asyncio

import pytest

from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import (
    _simple_count_resource,
    is_read_only_candidate,
    run_mcp_question,
)


SEVEN_TOOLS = {
    "find_endpoint", "describe_endpoint", "call", "raw_call",
    "memory_save", "memory_list", "memory_delete",
}


def tool(name, properties, required):
    schema = {"type": "object", "properties": properties, "required": required}
    return MCPToolInfo("ninjaone", name, f"ninjaone.{name}", name, schema)


class Manager:
    def __init__(self, selected):
        self.tools = [selected]
        self.calls = []

    def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True}


class LLM:
    def __init__(self, decision):
        self.decision = decision

    async def complete_json(self, system, prompt):
        return self.decision

    async def complete(self, system, prompt, temperature=0.0):
        return "Completed."


def test_all_seven_compatibility_tools_are_available_to_agent():
    for name in SEVEN_TOOLS:
        item = tool(name, {}, [])
        assert is_read_only_candidate(item), name


@pytest.mark.parametrize(
    "name,properties,required,arguments",
    [
        ("call", {"endpoint": {"type": "string"}}, ["endpoint"],
         {"endpoint": "POST /v2/devices"}),
        ("raw_call", {"request": {"type": "string"}}, ["request"],
         {"request": "POST /v2/devices"}),
    ],
)
def test_compatibility_api_write_calls_are_blocked(name, properties, required, arguments):
    selected = tool(name, properties, required)
    manager = Manager(selected)
    llm = LLM({"action": "call", "tool": f"ninjaone.{name}", "arguments": arguments})

    with pytest.raises(PermissionError, match="GET"):
        asyncio.run(run_mcp_question(llm, manager, "Create a device"))

    assert manager.calls == []


def test_memory_save_requires_explicit_user_intent():
    selected = tool(
        "memory_save",
        {"name": {"type": "string"}, "endpoint": {"type": "string"}},
        ["name", "endpoint"],
    )
    manager = Manager(selected)
    llm = LLM({
        "action": "call",
        "tool": "ninjaone.memory_save",
        "arguments": {"name": "Workstations", "endpoint": "GET /v2/devices"},
    })

    with pytest.raises(PermissionError, match="explicitly asks"):
        asyncio.run(run_mcp_question(llm, manager, "Show me all devices"))

    assert manager.calls == []



class CountManager:
    def __init__(self):
        self.tools = [
            tool("find_endpoint", {"query": {"type": "string"}}, ["query"]),
            tool("describe_endpoint", {"endpoint": {"type": "string"}}, ["endpoint"]),
            tool("call", {"endpoint": {"type": "string"}}, ["endpoint"]),
        ]
        self.calls = []

    def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "ninjaone.find_endpoint":
            return {
                "count": 1,
                "results": [{
                    "endpoint": "GET /v2/organizations",
                    "method": "GET",
                    "path": "/v2/organizations",
                    "summary": "List organizations",
                    "category": "Organizations",
                }],
            }
        if name == "ninjaone.describe_endpoint":
            return {
                "method": "GET",
                "path": "/v2/organizations",
                "parameters": [],
            }
        if name == "ninjaone.call":
            return {
                "endpoint": "GET /v2/organizations",
                "executed": True,
                "complete": True,
                "data": [{"id": 6}, {"id": 7}],
            }
        raise AssertionError(f"Unexpected tool call: {name}")


class NoLLM:
    async def complete_json(self, system, prompt):
        raise AssertionError("Simple count should not call OLMo.")

    async def complete(self, system, prompt, temperature=0.0):
        raise AssertionError("Simple count should not call OLMo.")


def test_plain_organization_count_uses_python_fast_path_without_llm():
    manager = CountManager()

    answer = asyncio.run(
        run_mcp_question(
            NoLLM(),
            manager,
            "How many organizations do we have in NinjaOne?",
        )
    )

    assert answer == "There are 2 organizations in NinjaOne."
    assert [name for name, _ in manager.calls] == [
        "ninjaone.find_endpoint",
        "ninjaone.describe_endpoint",
        "ninjaone.call",
    ]


def test_simple_count_detection_rejects_filtered_questions():
    assert _simple_count_resource("How many organizations do we have in NinjaOne?") == "organizations"
    assert _simple_count_resource("Count all devices") == "devices"
    assert _simple_count_resource("How many devices are offline?") is None
