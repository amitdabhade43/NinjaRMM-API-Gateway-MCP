# Local OLMo NinjaOne Agent

This branch adds a separate read-only agent application. It does not modify the NinjaOne MCP Gateway implementation under src/ninja_mcp.

## Install

    .\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
    .\.venv\Scripts\python.exe -m pip install -e .

## Configuration

The agent loads the repository-root .env without overwriting existing process variables.

Optional settings:

    NINJA_AGENT_FOUNDRY_URL=http://127.0.0.1:64541/v1
    NINJA_AGENT_MODEL=olmo-3-7b-instruct-generic-gpu
    NINJA_AGENT_API_KEY=local
    NINJA_AGENT_MCP_COMMAND=path-to-python.exe
    NINJA_AGENT_MCP_ARGS=-m ninja_mcp
    NINJA_AGENT_MAX_CANDIDATES=30
    NINJA_AGENT_MAX_PAGES=1000
    NINJA_AGENT_PAGE_SIZE=100

The NinjaOne device API uses cursor pagination with `after` and `pageSize`; the agent requests 50 records per page and follows the last record ID. The default cap is 1,000 pages (up to 50,000 records), after which it reports an explicit partial result rather than inventing a total. The final short or empty page is fetched to confirm completion, including when the total is an exact multiple of 50.

## Multiple MCP servers (Stage 1)

The agent now includes a generic MCP connection registry for multiple stdio servers. The default configuration remains the existing NinjaOne Gateway.

To inspect the tools exposed by configured servers without executing them:

    .\\.venv\\Scripts\\python.exe .\\ninjaone_agent.py --list-mcp-tools

To add more MCP servers, set `NINJA_AGENT_MCP_SERVERS_JSON` in the process environment or repository-root `.env`. Example:

    NINJA_AGENT_MCP_SERVERS_JSON=[{"name":"ninjaone","command":"C:\\project\\NinjaRMM-API-Gateway-MCP\\.venv\\Scripts\\python.exe","args":["-m","ninja_mcp"]},{"name":"filesystem","command":"node","args":["C:\\mcp\\filesystem\\server.js"],"env":{"FILESYSTEM_ROOT":"C:\\Data"}}]

Each server name must be unique. Tools are registered with server-qualified names such as `ninjaone.list_devices` and `filesystem.read_file`, so identical tool names from different servers do not collide. If one server fails to connect, the registry reports that server as unavailable and continues connecting to the others.

Stage 1 is discovery-only: `--list-mcp-tools` lists tool names, descriptions and input schemas. It does not execute tools. The existing NinjaOne question workflow remains unchanged in this stage.

## Run

Interactive:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py

Single question:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py --question "How many organizations and technicians do we have?"

## Safety

Only discover_endpoints, inspect_endpoint, execute_endpoint and execute_paginated_endpoint are exposed to the agent. Execution is GET-only. The agent does not call execute_raw_request, POST, PUT, PATCH or DELETE. Gateway-side validation remains authoritative.

## Tests

    .\.venv\Scripts\python.exe -m pytest tests/agent -q

Planner output is validated before use. API paths and parameters are selected from Gateway discovery and inspected against the OpenAPI schema. Device name filtering checks displayName, systemName, dnsName, netbiosName, name and hostname. Partial counts are never presented as confirmed totals.

## Generic MCP question mode (Stage 2 initial slice)

The generic selector can choose and invoke one relevant read-only tool from the configured MCP servers. It uses a lightweight lexical shortlist before asking OLMo to select a tool, validates required and unknown arguments against the discovered input schema, and uses server-qualified names.

    .\\.venv\\Scripts\\python.exe .\\ninjaone_agent.py --mcp-question "Find the NinjaOne API endpoint for listing devices"

This is an isolated test mode. The existing `--question` workflow remains the default and is unchanged. The first execution slice deliberately makes one tool call only; multi-step discovery/inspect/execute loops and additional result verification will be added after this mode is tested.

The generic selector uses a conservative name-based read-only filter. For NinjaOne, only discovery/inspection and endpoint execution tools are candidates, and endpoint execution is additionally restricted to arguments beginning with `GET `. Gateway-side approval and method enforcement remain authoritative. Do not expose write-capable MCP servers to this mode until explicit per-tool permissions are configured.
