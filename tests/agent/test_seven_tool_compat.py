import asyncio

import pytest

from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import (
    _simple_count_resource,
    _simple_name_resource,
    is_read_only_candidate,
    run_mcp_question,
)
from ninjaone_agent.llm import LocalLLM
from ninjaone_agent.chat import should_use_mcp


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
def test_compatibility_api_write_calls_require_confirmation(name, properties, required, arguments):
    selected = tool(name, properties, required)
    manager = Manager(selected)
    llm = LLM({"action": "call", "tool": f"ninjaone.{name}", "arguments": arguments})

    answer = asyncio.run(run_mcp_question(
        llm, manager, "Create a device",
        approval_callback=lambda operation, body: False,
    ))
    assert answer.startswith("Cancelled.")
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


class ScriptedLLM:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    async def complete_json(self, system, prompt):
        assert self.decisions, "Unexpected extra OLMo decision"
        return self.decisions.pop(0)

    async def complete(self, system, prompt, temperature=0.0):
        return "OLMo final answer based on NinjaOne results."


def test_plain_organization_count_uses_olmo_tool_reasoning():
    manager = CountManager()

    llm = ScriptedLLM([
        {"action": "call", "tool": "ninjaone.find_endpoint", "arguments": {"query": "list organizations"}},
        {"action": "call", "tool": "ninjaone.describe_endpoint", "arguments": {"endpoint": "GET /v2/organizations"}},
        {"action": "call", "tool": "ninjaone.call", "arguments": {"endpoint": "GET /v2/organizations"}},
        {"action": "final", "answer": "NinjaOne has 2 organizations."},
    ])
    answer = asyncio.run(run_mcp_question(
        llm, manager, "How many organizations do we have in NinjaOne?"
    ))

    assert answer == "NinjaOne has 2 organizations."
    assert llm.decisions == []
    assert [name for name, _ in manager.calls] == [
        "ninjaone.find_endpoint",
        "ninjaone.describe_endpoint",
        "ninjaone.call",
    ]


def test_simple_count_detection_rejects_filtered_questions():
    assert _simple_count_resource("How many organizations do we have in NinjaOne?") == "organizations"
    assert _simple_count_resource("Count all devices") == "devices"
    assert _simple_count_resource("How many devices are offline?") is None



def test_organization_name_question_with_typo_routes_to_mcp():
    question = "can i ninjaone oraganization name?"
    assert should_use_mcp(question) is True
    assert _simple_name_resource(question) == "organizations"


def test_local_llm_repairs_missing_quote_before_json_key_colon():
    malformed = '{"action":"call","tool":"ninjaone.find_endpoint","arguments":{"query:"organization name in NinjaOne"}}'
    parsed = LocalLLM._parse_json_object(malformed)
    assert parsed["arguments"]["query"] == "organization name in NinjaOne"


class NameManager(CountManager):
    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "ninjaone.find_endpoint":
            return {
                "count": 2,
                "results": [
                    {
                        "endpoint": "GET /v2/organizations",
                        "method": "GET",
                        "path": "/v2/organizations",
                        "summary": "List organizations",
                        "category": "Organizations",
                    },
                    {
                        "endpoint": "POST /v2/organizations",
                        "method": "POST",
                        "path": "/v2/organizations",
                        "summary": "Create organization",
                        "category": "Organizations",
                    },
                ],
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
                "data": [
                    {"id": 6, "name": "HOERBIGER"},
                    {"id": 7, "name": "HOERBIGER - Unattended"},
                ],
            }
        raise AssertionError(f"Unexpected tool call: {name}")


def test_simple_organization_name_lookup_uses_olmo_tool_reasoning():
    manager = NameManager()
    llm = ScriptedLLM([
        {"action": "call", "tool": "ninjaone.find_endpoint", "arguments": {"query": "organization names in NinjaOne"}},
        {"action": "call", "tool": "ninjaone.describe_endpoint", "arguments": {"endpoint": "GET /v2/organizations"}},
        {"action": "call", "tool": "ninjaone.call", "arguments": {"endpoint": "GET /v2/organizations"}},
        {"action": "final", "answer": "NinjaOne has two organizations: HOERBIGER and HOERBIGER - Unattended."},
    ])
    answer = asyncio.run(run_mcp_question(
        llm, manager, "can i ninjaone oraganization name?"
    ))
    assert "HOERBIGER" in answer
    assert "HOERBIGER - Unattended" in answer
    assert llm.decisions == []
