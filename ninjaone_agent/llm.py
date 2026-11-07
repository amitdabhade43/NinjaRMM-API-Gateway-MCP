"""Small OpenAI-compatible client for Foundry Local."""
from __future__ import annotations
import json
from typing import Any, AsyncIterator
from openai import AsyncOpenAI
from .config import AgentConfig

class LocalLLM:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = AsyncOpenAI(base_url=config.foundry_url, api_key=config.api_key,
                                  timeout=config.request_timeout, max_retries=0)

    async def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        raw = (await self.complete(system, user)).strip()
        if raw.startswith(chr(96) * 3):
            raw = raw.split("\n", 1)[-1].rsplit(chr(96) * 3, 1)[0].strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("OLMo did not return a JSON object.")
            value = json.loads(raw[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError("OLMo plan must be a JSON object.")
        return value

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2, stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def close(self) -> None:
        await self.client.close()
