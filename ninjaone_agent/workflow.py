"""LangGraph orchestration for the local OLMo + NinjaOne MCP agent.

OLMo owns intent interpretation, task decomposition, tool selection, result
interpretation and final natural-language generation. Python only orchestrates
the graph, validates and executes MCP calls, and enforces write permissions.
"""
from __future__ import annotations

import json
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .mcp_tool_agent import run_mcp_question
from .mcp_registry import MultiMCPManager


class AgentState(TypedDict, total=False):
    question: str
    conversation_context: str
    plan: dict[str, Any]
    plan_error: str
    answer: str


PLAN_SYSTEM = """You are OLMo, the reasoning and planning brain of a NinjaOne operations agent.
Understand the user's request, correct obvious spelling mistakes, and use conversation context.
Examples: "technicain" means "technician"; "oraganization" means "organization".
In NinjaOne, a technician is a human staff/technician account, NOT a device label or device type.
Never reinterpret a named NinjaOne resource as a device label unless the user explicitly says label.
Return ONLY a compact valid JSON object with exactly these keys:
{"intent":"...","tasks":["..."],"needs_clarification":false}
Use a short string for each task, not nested objects. For a clear read/count/list request, needs_clarification must be false.
Do not ask for clarification merely because the user misspelled a known resource.
Do not choose API paths here; the tool-using agent will discover the correct operation from the NinjaOne API catalogue."""


async def run_agent_workflow(
    llm,
    manager: MultiMCPManager,
    question: str,
    conversation_context: str = "",
    approval_callback=None,
    on_plan: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Execute understand -> OLMo tool-agent -> final answer as a LangGraph."""
    async def understand(state: AgentState) -> dict[str, Any]:
        prompt = (
            "CONVERSATION CONTEXT:\n" + (state.get("conversation_context") or "None")
            + "\n\nUSER REQUEST:\n" + state["question"]
        )
        # Planning is helpful for visibility, but malformed planner JSON must
        # never prevent the tool-using OLMo agent from answering the original request.
        try:
            plan = await llm.complete_json(PLAN_SYSTEM, prompt)
            if not isinstance(plan.get("tasks"), list):
                raise ValueError("OLMo planner did not return a tasks array.")
            if on_plan:
                on_plan(plan)
            return {"plan": plan}
        except ValueError as exc:
            fallback = {
                "status": "planner_fallback",
                "reason": str(exc),
                "message": "Planner output was invalid; the OLMo tool agent will reason from the original request.",
            }
            if on_plan:
                on_plan(fallback)
            return {"plan": {}}

    async def agent(state: AgentState) -> dict[str, Any]:
        plan = state.get("plan") or {}
        context = state.get("conversation_context") or ""
        if plan and plan.get("status") != "planner_fallback":
            context += (
                "\n\nOLMo PLANNING NOTES (the original user request is authoritative; "
                "correct any mistaken interpretation in these notes):\n"
                + json.dumps(plan, ensure_ascii=False, default=str)
            )
        # The tool-using OLMo agent decides whether clarification is genuinely
        # required. A preliminary planner must not block a clear live-data request.
        answer = await run_mcp_question(
            llm, manager, state["question"],
            conversation_context=context,
            approval_callback=approval_callback,
        )
        return {"answer": answer}

    graph = StateGraph(AgentState)
    graph.add_node("understand", understand)
    graph.add_node("agent", agent)
    graph.set_entry_point("understand")
    graph.add_edge("understand", "agent")
    graph.add_edge("agent", END)
    app = graph.compile()
    result = await app.ainvoke({
        "question": question,
        "conversation_context": conversation_context,
    })
    return str(result.get("answer") or "OLMo did not produce an answer.")
