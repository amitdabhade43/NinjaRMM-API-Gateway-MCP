"""Fast, predictable routing between local chat and NinjaOne MCP operations."""
from __future__ import annotations

import re

_RESOURCE_WORDS = {
    "device", "devices", "machine", "machines", "computer", "computers",
    "user", "users", "technician", "technicians", "organization", "organizations",
    "org", "orgs", "location", "locations", "group", "groups", "role", "roles",
    "policy", "policies", "alert", "alerts", "activity", "activities", "job", "jobs",
    "script", "scripts", "patch", "patches", "backup", "backups", "software",
    "inventory", "warranty", "ticket", "tickets", "endpoint", "endpoints",
}
_OPERATION_WORDS = {
    "show", "list", "find", "search", "get", "fetch", "retrieve", "count",
    "display", "check", "report", "export", "filter", "identify", "locate",
    "view", "details", "detail", "status", "installed", "missing", "failed",
    "offline", "online", "active", "inactive", "whose", "starting", "starts",
    "beginning", "ending", "ends", "assigned", "belonging", "older", "newer",
    "all", "every", "which",
}
_GREETING_ONLY = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|thanks|thank you|"
    r"bye|goodbye|how are you|what can you do)[!.? ]*$",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(it|they|them|those|these|that|this|same|above|details|more|also|"
    r"their|its|show me|open|explain the result)\b",
    re.IGNORECASE,
)


def should_use_mcp(question: str, previous_mode: str | None = None) -> bool:
    """Route operational inventory requests to MCP; keep normal conversation in OLMo."""
    value = question.strip()
    if not value or _GREETING_ONLY.fullmatch(value):
        return False

    words = set(re.findall(r"[a-z0-9]+", value.casefold()))
    has_resource = bool(words & _RESOURCE_WORDS)
    has_operation = bool(words & _OPERATION_WORDS)

    if has_resource and has_operation:
        return True

    # Explicit NinjaOne/RMM operational phrasing should use the gateway.
    mentions_platform = bool(re.search(r"\b(ninja\s*one|ninjaone|rmm)\b", value, re.I))
    if mentions_platform and has_operation:
        return True

    # Short follow-ups inherit the previous operational context, except greetings.
    if previous_mode == "mcp" and len(words) <= 10 and _FOLLOW_UP.search(value):
        return True

    return False


def format_conversation_context(messages: list[dict[str, str]], limit: int = 6) -> str:
    """Create a small context window for operational follow-up requests."""
    recent = [item for item in messages if item.get("role") in {"user", "assistant"}][-limit:]
    return "\n".join(
        f"{item['role'].capitalize()}: {item.get('content', '')[:1200]}"
        for item in recent
    )
