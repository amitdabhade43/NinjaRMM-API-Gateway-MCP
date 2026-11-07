# Local OLMo NinjaOne Agent

This branch adds a separate read-only agent application. It does not modify the NinjaOne MCP Gateway implementation under src/ninja_mcp.

## Install

Use the existing project virtual environment and install the agent dependency:

    .\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt

The MCP SDK is already a project dependency. Install the repository in editable mode if the current environment has not installed it:

    .\.venv\Scripts\python.exe -m pip install -e .

## Configuration

The agent loads the repository-root .env without overwriting existing process variables.

Optional agent settings:

    NINJA_AGENT_FOUNDRY_URL=http://127.0.0.1:64541/v1
    NINJA_AGENT_MODEL=olmo-3-7b-instruct-generic-gpu
    NINJA_AGENT_API_KEY=local
    NINJA_AGENT_MCP_COMMAND=path-to-python.exe
    NINJA_AGENT_MCP_ARGS=-m ninja_mcp
    NINJA_AGENT_MAX_CANDIDATES=30
    NINJA_AGENT_MAX_PAGES=10
    NINJA_AGENT_PAGE_SIZE=100

The defaults match the previously tested local OLMo model and the gateway launched from the same Python environment. The gateway continues to load NinjaOne credentials from the existing .env. Do not commit .env.

## Run

Interactive:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py

Single question:

    .\.venv\Scripts\python.exe .\ninjaone_agent.py --question "How many organizations and technicians do we have?"

## Safety boundary

The agent exposes only discover_endpoints, inspect_endpoint, execute_endpoint and execute_paginated_endpoint to its workflow. It executes GET only. It does not call execute_raw_request, POST, PUT, PATCH or DELETE. Gateway-side validation and security remain authoritative.

## Tests

    .\.venv\Scripts\python.exe -m pytest tests/agent -q

Planner output is validated before use. API paths are always selected from Gateway discovery results and inspected against the OpenAPI schema. Python applies requested filters and counts, and preserves Gateway completeness metadata.
