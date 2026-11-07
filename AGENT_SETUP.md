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
    [MCP] Connected: ninjaone (5 tools discovered)
    [MCP] Working...
    Assistant: ...

    You: Show me their details
    Assistant: ...

The router is intentionally lightweight and deterministic. It uses NinjaOne resource/action wording and the previous turn to recognize common operational follow-ups; it does not spend an extra model call classifying every message.

## MCP tool access and safety

The current NinjaOne Gateway exposes five tools to the OLMo agent:

| Tool | Agent access |
|---|---|
| `discover_endpoints` | Allowed |
| `inspect_endpoint` | Allowed |
| `execute_endpoint` | GET only |
| `execute_paginated_endpoint` | GET only |
| `execute_raw_request` | GET only |

The agent can discover and inspect the OpenAPI operations, then select the appropriate execution tool. Raw requests are permitted only when the request begins with `GET `. The Gateway remains the final authority for method, schema and approval checks.

POST, PUT and PATCH are not automatically invoked by the agent. The Gateway requires a trusted, short-lived human approval token for those methods. DELETE is permanently blocked. Do not bypass these restrictions to make a demo appear more capable.

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
