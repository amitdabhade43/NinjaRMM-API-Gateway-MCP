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
Understand the user's natural-language request, including spelling mistakes and follow-up context.
Decompose it into the smallest useful sequence of tasks. Do not invent API paths or claim data.
Return exactly one JSON object with these keys:
{
  "intent": "short description",
  "tasks": [{"goal": "what data/action is needed", "resource": "likely NinjaOne resource",
             "operation": "read|create|update|delete|unknown",
             "filters": [], "fields": [], "depends_on": []}],
  "answer_requirements": ["what the final answer must contain"],
  "needs_clarification": false,
  "clarification_question": ""
}
For ordinary read requests, create one task. For multi-part requests, create ordered dependent tasks.
If the request is ambiguous in a way that prevents safe execution, set needs_clarification=true.
Do not select a concrete endpoint here; the tool-using agent will discover it from the full API catalogue."""


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
        plan = await llm.complete_json(PLAN_SYSTEM, prompt)
        if not isinstance(plan.get("tasks"), list):
            raise ValueError("OLMo planner did not return a tasks array.")
        if on_plan:
            on_plan(plan)
        return {"plan": plan}

    async def agent(state: AgentState) -> dict[str, Any]:
        plan_text = json.dumps(state["plan"], ensure_ascii=False, default=str)
        context = (state.get("conversation_context") or "") + (
            "\n\nOLMo DECOMPOSED EXECUTION PLAN (follow this intent; discover actual endpoints):\n"
            + plan_text
        )
        if state["plan"].get("needs_clarification"):
            return {"answer": str(state["plan"].get("clarification_question") or
                                  "Could you clarify what you want to retrieve or change?")}
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
