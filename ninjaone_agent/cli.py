"""CLI workflow: conversational OLMo chat with lazy, reusable MCP operations."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback

from .config import AgentConfig, PROJECT_ROOT
from .executor import execute_plan
from .llm import LocalLLM
from .mcp_gateway import GatewayConnection
from .mcp_registry import MCPServerConfig, MultiMCPManager
from .mcp_tool_agent import run_mcp_question
from .planner import create_plan
from .response import format_response
from .chat import format_conversation_context, should_use_mcp

CHAT_SYSTEM = (
    "You are a helpful local NinjaOne operations assistant running on OLMo. "
    "Answer normal questions conversationally and directly. You can explain "
    "NinjaOne concepts, help with troubleshooting, and discuss results from "
    "earlier turns. Do not claim to have queried live NinjaOne data unless the "
    "MCP tools were actually called. If the user asks for live tenant data, "
    "the chat router will send that request to the MCP tools."
)


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
            answer = await run_mcp_question(llm, manager, question)
        print("\nResult\n------", flush=True)
        print(answer, flush=True)
        return 0
    finally:
        await llm.close()


async def run_question(question: str) -> int:
    """Legacy one-shot planner retained for backward compatibility."""
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


async def run_chat_session() -> int:
    """Interactive chat: direct OLMo for conversation, MCP only for live operations."""
    config = AgentConfig.from_env()
    llm = LocalLLM(config)
    servers = MCPServerConfig.load_all(config.mcp_command, config.mcp_args)
    manager = None
    history: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM}]
    previous_mode: str | None = None

    print("NinjaOne OLMo Assistant")
    print("Chat normally, or ask for live NinjaOne data. Type 'exit' to quit.")
    try:
        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if question.casefold() in {"exit", "quit"}:
                break
            if not question:
                continue

            try:
                if should_use_mcp(question, previous_mode):
                    # Start the stdio MCP process only on the first operational
                    # request, then reuse the connection for the rest of the chat.
                    if manager is None:
                        print("[MCP] Connecting to NinjaOne Gateway...", flush=True)
                        manager = MultiMCPManager(servers)
                        await manager.__aenter__()
                        status = manager.server_status()
                        print(
                            f"[MCP] Connected: {', '.join(status['connected'])} "
                            f"({status['tool_count']} tools discovered)",
                            flush=True,
                        )
                    context = format_conversation_context(history)
                    print("[MCP] Working...", flush=True)
                    answer = await run_mcp_question(
                        llm, manager, question, conversation_context=context
                    )
                    previous_mode = "mcp"
                else:
                    history.append({"role": "user", "content": question})
                    # Keep the system prompt and only the latest five turns.
                    history = [history[0]] + history[-10:]
                    print("[OLMo] Thinking...", flush=True)
                    answer = await llm.chat(history)
                    previous_mode = "chat"

                print(f"\nAssistant: {answer}", flush=True)
                if history[-1].get("role") != "user" or history[-1].get("content") != question:
                    history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": answer})
                history = [history[0]] + history[-10:]
            except Exception as exc:
                print(f"\n[Error] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                # Keep the session alive so a single failed request does not
                # terminate the demonstration.
                previous_mode = None
    finally:
        if manager is not None:
            await manager.__aexit__(None, None, None)
        await llm.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Local OLMo NinjaOne natural-language agent")
    parser.add_argument("-q", "--question", help="Run one request through the legacy planner and exit")
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
        asyncio.run(run_chat_session())
    except Exception as exc:
        print(f"Agent error: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
