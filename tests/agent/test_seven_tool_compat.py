import asyncio

import pytest

from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import is_read_only_candidate, run_mcp_question


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
