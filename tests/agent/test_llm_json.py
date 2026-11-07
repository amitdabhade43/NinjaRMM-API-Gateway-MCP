import asyncio

import pytest

from ninjaone_agent.llm import LocalLLM


class FakeLLM(LocalLLM):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    async def complete(self, system, user, temperature=0.0):
        self.calls += 1
        return next(self.responses)


def test_complete_json_retries_malformed_response_once():
    llm = FakeLLM([
        '{"action":"call", "tool" "ninjaone.discover_endpoints"}',
        '{"action":"call","tool":"ninjaone.discover_endpoints","arguments":{"intent":"list devices"}}',
    ])

    result = asyncio.run(llm.complete_json("system", "user request"))

    assert result == {
        "action": "call",
        "tool": "ninjaone.discover_endpoints",
        "arguments": {"intent": "list devices"},
    }
    assert llm.calls == 2


def test_complete_json_accepts_fenced_json_without_retry():
    llm = FakeLLM(['```json\n{"action":"final","answer":"Done"}\n```'])

    result = asyncio.run(llm.complete_json("system", "user request"))

    assert result == {"action": "final", "answer": "Done"}
    assert llm.calls == 1


def test_complete_json_stops_after_second_invalid_response():
    llm = FakeLLM(["not json", "still not json"])

    with pytest.raises(ValueError, match="invalid JSON twice"):
        asyncio.run(llm.complete_json("system", "user request"))

    assert llm.calls == 2



def test_complete_json_ignores_extra_closing_brace_after_valid_object():
    llm = FakeLLM([
        '{"action": "discover_endpoints", "tool": "ninjaone.discover_endpoints", '
        '"arguments": {"intent": "find devices whose names start with 2QN"}}}',
    ])

    result = asyncio.run(llm.complete_json("system", "user request"))

    assert result == {
        "action": "discover_endpoints",
        "tool": "ninjaone.discover_endpoints",
        "arguments": {"intent": "find devices whose names start with 2QN"},
    }
    assert llm.calls == 1
