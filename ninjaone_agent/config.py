"""Agent configuration. Secrets remain local and are never committed."""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)

@dataclass(frozen=True)
class AgentConfig:
    foundry_url: str
    model: str
    api_key: str
    mcp_command: str
    mcp_args: tuple[str, ...]
    max_candidates: int = 30
    max_pages: int = 1000
    page_size: int = 100
    request_timeout: float = 45.0

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            foundry_url=os.getenv("NINJA_AGENT_FOUNDRY_URL", os.getenv("FOUNDRY_URL", "http://127.0.0.1:64541/v1")).rstrip("/"),
            model=os.getenv("NINJA_AGENT_MODEL", os.getenv("FOUNDRY_MODEL", "olmo-3-7b-instruct-generic-gpu")),
            api_key=os.getenv("NINJA_AGENT_API_KEY", "local"),
            mcp_command=os.getenv("NINJA_AGENT_MCP_COMMAND", sys.executable),
            mcp_args=tuple(os.getenv("NINJA_AGENT_MCP_ARGS", "-m ninja_mcp").split()),
            max_candidates=max(1, int(os.getenv("NINJA_AGENT_MAX_CANDIDATES", "30"))),
            # Device inventory is cursor-paginated in 50-record pages. 1,000
            # pages allow up to 50,000 records, followed by a short-page check.
            # The explicit cap prevents an accidental endless cursor loop.
            max_pages=max(1, min(2000, int(os.getenv("NINJA_AGENT_MAX_PAGES", "1000")))),
            page_size=max(1, min(200, int(os.getenv("NINJA_AGENT_PAGE_SIZE", "100")))),
            request_timeout=float(os.getenv("NINJA_AGENT_TIMEOUT", "45")),
        )
