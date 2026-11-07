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
