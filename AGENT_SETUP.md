# Local OLMo NinjaOne Assistant

The agent uses the existing local OLMo model and the NinjaOne API Gateway MCP server. It does not use cloud model APIs and does not replace the Gateway.

## Install

Run from the repository root in Windows PowerShell:

    .\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

## Configuration

The agent loads the repository-root .env without overwriting existing process variables.

    NINJA_AGENT_FOUNDRY_URL=http://127.0.0.1:64541/v1
    NINJA_AGENT_MODEL=olmo-3-7b-instruct-generic-gpu
    NINJA_AGENT_API_KEY=local
    NINJA_AGENT_MCP_COMMAND=C:\project\NinjaRMM-API-Gateway-MCP\.venv\Scripts\python.exe
    NINJA_AGENT_MCP_ARGS=-m ninja_mcp
    NINJA_AGENT_MAX_CANDIDATES=30
    NINJA_AGENT_MAX_PAGES=1000
    NINJA_AGENT_PAGE_SIZE=100
    NINJA_AGENT_TIMEOUT=45

Keep NinjaOne credentials in .env or process environment. Never commit credentials.

## Run the assistant

Start the interactive assistant:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py

The default interactive mode has two automatic paths:

- **General chat:** greetings, explanations, troubleshooting guidance and normal follow-up conversation go directly to OLMo. No MCP call or planner call is made.
- **NinjaOne operations:** requests for live tenant data are routed to the MCP tool agent. The MCP process starts only on the first operational request and stays connected for the rest of the session.

Examples:

    You: hi
    Assistant: Hello! How can I help?

    You: What is NinjaOne patch management?
    Assistant: ...

    You: Show me all devices
    [MCP] Connecting to NinjaOne Gateway...
    [MCP] Connected: ninjaone (12 tools discovered)
    [MCP] Working...
    Assistant: ...

    You: Show me their details
    Assistant: ...

The router is intentionally lightweight and deterministic. It uses NinjaOne resource/action wording and the previous turn to recognize common operational follow-ups; it does not spend an extra model call classifying every message.

## MCP tool access and safety

The Gateway exposes the original five workflow tools plus seven compatibility tools inspired by the reference repository:

| Compatibility tool | Purpose |
|---|---|
| `find_endpoint` | Fuzzy search for a NinjaOne API operation |
| `describe_endpoint` | Inspect exact endpoint parameters and schemas |
| `call` | Execute a documented endpoint |
| `raw_call` | Execute a concrete relative API path |
| `memory_save` | Save a reusable GET query template locally |
| `memory_list` | List saved query templates |
| `memory_delete` | Delete a saved query template |

The original `discover_endpoints`, `inspect_endpoint`, `execute_endpoint`, `execute_paginated_endpoint` and `execute_raw_request` tools remain available. The compatibility tools are thin aliases over the same OpenAPI-driven Gateway; they do not add endpoint coverage or create a second API client.

The OLMo agent may execute only GET requests against the NinjaOne tenant. Both `call` and `raw_call` are subject to that rule. Saved-query memory is local to the machine (default: `~/.ninjaone_agent/saved_queries.json`) and stores only the endpoint plus path/query parameters and a description—not tenant response data or credentials. Saving or deleting a template requires explicit user wording.

The Gateway remains the final authority for method, schema and approval checks. POST, PUT and PATCH still require a trusted, short-lived human approval token; DELETE remains blocked. We are not weakening these existing protections as part of the functionality work.

For additional configured MCP servers, the default policy allows tools whose names use read-style prefixes such as `get_`, `list_`, `search_`, `read_`, `inspect_` and `fetch_`. Review each server's permissions before connecting write-capable tools.

## Useful commands

List tools and schemas without executing them:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py --list-mcp-tools

Run one request directly through the generic MCP tool agent:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py --mcp-question "Find devices whose names start with 2QN"

Run the legacy planner for comparison/backward compatibility:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py --question "How many organizations and technicians do we have?"

The default interactive command is the recommended showcase entry point. The legacy `--question` option is retained but is not the default chat workflow.

## Performance and result correctness

- The local model is initialized once per interactive session.
- General chat does not start an MCP process.
- The MCP connection is created on demand and reused across operational turns.
- Tool schemas are compacted before being sent to OLMo; the full schema is still used for Python-side argument validation.
- The tool loop is bounded (4 steps by default) and avoids repeating identical calls.
- Record filters are applied deterministically in Python rather than asking OLMo to scan large JSON responses.
- Pagination/completeness metadata must be preserved. Never report a partial page as a complete tenant-wide count.
- Conversation context is bounded to the latest five turns to keep local inference prompts manageable.

## Tests

Run all tests:

    .\.venv\Scripts\python.exe -m pytest -q

Run agent-specific tests:

    .\.venv\Scripts\python.exe -m pytest tests/agent -q
