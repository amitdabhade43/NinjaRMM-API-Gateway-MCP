import asyncio
import json

from ninjaone_agent.mcp_registry import MCPToolInfo
from ninjaone_agent.mcp_tool_agent import run_mcp_question


class _Manager:
    def __init__(self):
        self.tools = [
            MCPToolInfo(
                "ninjaone", "execute_endpoint", "ninjaone.execute_endpoint",
                "Execute a discovered GET endpoint",
                {"type": "object", "properties": {"endpoint": {"type": "string"}},
                 "required": ["endpoint"]},
            )
        ]

    def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        return {"data": [
            {"id": 1, "systemName": "2QN-PC"},
            {"id": 2, "systemName": "ABC-PC"},
        ]}


class _LLM:
    def __init__(self):
        self.final_prompt = ""

    async def complete_json(self, system, user):
        return {
            "action": "call",
            "tool": "ninjaone.execute_endpoint",
            "arguments": {"endpoint": "GET /v2/devices"},
            "filters": [
                {"field": "systemName", "operator": "begins with", "value": "2QN"}
            ],
        }

    async def complete(self, system, user, temperature=0.0):
        self.final_prompt = user
        return "Found one matching device."


def test_mcp_agent_applies_natural_language_filter_to_tool_records():
    llm = _LLM()
    answer = asyncio.run(
        run_mcp_question(llm, _Manager(), "Show devices beginning with 2QN", max_steps=1)
    )

    assert answer == "Found one matching device."
    assert '"matched": 1' in llm.final_prompt
    assert '"examined": 2' in llm.final_prompt
    assert '"systemName": "2QN-PC"' in llm.final_prompt
    assert '"systemName": "ABC-PC"' not in llm.final_prompt
