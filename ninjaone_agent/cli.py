"""CLI workflow: plan once, execute read-only MCP tasks, respond quickly."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from .config import AgentConfig, PROJECT_ROOT
from .executor import execute_plan
from .llm import LocalLLM
from .mcp_gateway import GatewayConnection
from .mcp_registry import MCPServerConfig, MultiMCPManager
from .mcp_tool_agent import run_mcp_question
from .planner import create_plan
from .response import format_response

async def list_mcp_tools() -> int:
    config = AgentConfig.from_env()
    servers = MCPServerConfig.load_all(config.mcp_command, config.mcp_args)
    async with MultiMCPManager(servers) as manager:
        status = manager.server_status()
        print("MCP server status", flush=True)
        print(json.dumps(status, indent=2), flush=True)
        print("\nDiscovered tools", flush=True)
        for tool in manager.list_tools():
            print(f"\n[{tool.qualified_name}] {tool.description}", flush=True)
            print(json.dumps(tool.input_schema, ensure_ascii=False), flush=True)
    return 0


async def run_generic_mcp_question(question: str) -> int:
    config = AgentConfig.from_env()
    llm = LocalLLM(config)
    try:
        servers = MCPServerConfig.load_all(config.mcp_command, config.mcp_args)
        print("Connecting to configured MCP servers...", flush=True)
        async with MultiMCPManager(servers) as manager:
            print("Connected:", ", ".join(manager.server_status()["connected"]), flush=True)
            print("Selecting a relevant read-only tool...", flush=True)
            answer = await run_mcp_question(llm, manager, question)
        print("\nResult\n------", flush=True)
        print(answer, flush=True)
        return 0
    finally:
        await llm.close()


async def run_question(question: str) -> int:
    config = AgentConfig.from_env()
    os.chdir(PROJECT_ROOT)
    llm = LocalLLM(config)
    try:
        print("Understanding request...", flush=True)
        plan = await create_plan(llm, question)
        print(f"Plan ready: {len(plan['tasks'])} task(s). Connecting to NinjaOne Gateway...", flush=True)
        async with GatewayConnection(config) as gateway:
            print("Gateway connected. Executing read-only tasks...", flush=True)
            def show_progress(result):
                task = result["task"]
                if result.get("status") == "success" and "count" in result:
                    if result.get("complete", True):
                        print(f"[completed] {task['description']}: {result['count']} match(es)", flush=True)
                    else:
                        pages = result.get("pages_fetched")
                        page_note = f" across {pages} page(s)" if pages else ""
                        print(
                            f"[partial] {task['description']}: {result['count']} match(es) "
                            f"among {result.get('total_records_received', 0)} record(s) checked{page_note}",
                            flush=True,
                        )
                elif result.get("status") == "success":
                    print(f"[completed] {task['description']}", flush=True)
                else:
                    print(f"[failed] {task['description']}: {result.get('error')}", flush=True)
            results = await execute_plan(gateway, config, plan, on_task_complete=show_progress)
        print("\nResult\n------", flush=True)
        print(await format_response(llm, plan, results), flush=True)
        return 0 if all(item.get("status") == "success" for item in results) else 1
    finally:
        await llm.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Local OLMo NinjaOne natural-language agent")
    parser.add_argument("-q", "--question", help="Run one question and exit")
    parser.add_argument("--list-mcp-tools", action="store_true",
                        help="Connect configured MCP servers and list their tools without executing them")
    parser.add_argument("--mcp-question", help="Run one request through the generic read-only MCP tool selector")
    args = parser.parse_args()
    try:
        if args.list_mcp_tools:
            asyncio.run(list_mcp_tools())
            return
        if args.mcp_question:
            asyncio.run(run_generic_mcp_question(args.mcp_question))
            return
        if args.question:
            asyncio.run(run_question(args.question))
            return
        print("NinjaOne OLMo Agent — type exit to quit.")
        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question.casefold() in {"exit", "quit"}:
                break
            if question:
                asyncio.run(run_question(question))
    except Exception as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
