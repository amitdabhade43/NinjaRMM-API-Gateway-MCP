"""Small OpenAI-compatible client for Foundry Local."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from .config import AgentConfig


class LocalLLM:
    def __init__(self, config: AgentConfig):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Agent dependency missing. Install it with: "
                "python -m pip install -r requirements-agent.txt"
            ) from exc
        self.config = config
        self.client = AsyncOpenAI(
            base_url=config.foundry_url,
            api_key=config.api_key,
            timeout=config.request_timeout,
            max_retries=0,
        )

    async def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        """Parse a JSON object, allowing a surrounding Markdown code fence/prose."""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("OLMo did not return a JSON object.")
            try:
                value = json.loads(raw[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"OLMo returned invalid JSON (line {exc.lineno}, "
                    f"column {exc.colno})."
                ) from exc

        if not isinstance(value, dict):
            raise ValueError("OLMo response must be a JSON object.")
        return value

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Request JSON and make one low-cost repair attempt if OLMo formats it badly."""
        raw = await self.complete(system, user)
        try:
            return self._parse_json_object(raw)
        except ValueError as first_error:
            repair_system = (
                "Return exactly one valid JSON object. Do not include Markdown, "
                "explanations, comments, or text before or after the JSON. "
                "Use double quotes for every JSON key and string. Escape "
                "newlines inside strings. Follow the requested JSON structure."
            )
            repair_user = (
                "Your previous response was not valid JSON. Correct the response "
                "for the original request below. Return only the corrected JSON.\n\n"
                "ORIGINAL SYSTEM INSTRUCTIONS:\n"
                + system
                + "\n\nORIGINAL REQUEST:\n"
                + user
                + "\n\nINVALID RESPONSE:\n"
                + raw[:6000]
            )
            repaired = await self.complete(repair_system, repair_user)
            try:
                return self._parse_json_object(repaired)
            except ValueError as second_error:
                first_excerpt = repr(raw[:1000])
                repaired_excerpt = repr(repaired[:1000])
                raise ValueError(
                    "OLMo returned invalid JSON twice; no MCP tool was executed. "
                    f"First error: {first_error}; second error: {second_error}. "
                    f"First response excerpt: {first_excerpt}. "
                    f"Repair response excerpt: {repaired_excerpt}"
                ) from second_error

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def close(self) -> None:
        await self.client.close()
