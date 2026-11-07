from ninjaone_agent.chat import format_conversation_context, should_use_mcp


def test_greetings_and_general_questions_stay_in_local_chat():
    assert not should_use_mcp("hi")
    assert not should_use_mcp("What is NinjaOne?")
    assert not should_use_mcp("Explain device compliance")


def test_live_ninjaone_resource_requests_use_mcp():
    assert should_use_mcp("Show me all devices")
    assert should_use_mcp("Find devices whose names start with 2QN")
    assert should_use_mcp("How many organizations do we have?")
    assert should_use_mcp("List users assigned to this organization")


def test_short_follow_up_uses_previous_mcp_context():
    assert should_use_mcp("Show me their details", previous_mode="mcp")
    assert not should_use_mcp("thanks", previous_mode="mcp")


def test_context_is_bounded_and_excludes_system_message():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "List devices"},
        {"role": "assistant", "content": "Found devices"},
    ]
    context = format_conversation_context(messages)
    assert "User: List devices" in context
    assert "Assistant: Found devices" in context
    assert "system" not in context
