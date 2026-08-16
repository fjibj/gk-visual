"""Anthropic Messages API provider（覆盖火山引擎 Coding Plan 等 Anthropic 兼容端点）。

关键点：推理模型（如 kimi-k2.6）会在 content 里先吐 thinking 块，这里只取 text 块。
"""

from __future__ import annotations

import httpx

from ..config import LLMConfig


def make_anthropic_llm(cfg: LLMConfig):
    base_url = cfg.base_url.rstrip("/")
    model = cfg.model
    api_key = cfg.api_key
    max_tokens = cfg.max_tokens
    disable_thinking = cfg.disable_thinking

    async def llm_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        keyword_extraction=False,
        **kwargs,
    ) -> str:
        messages = []
        system = system_prompt
        for m in history_messages or []:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system = (system + "\n\n" + content) if system else content
            else:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        if disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.post(f"{base_url}/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        chunks = [
            b.get("text", "")
            for b in data.get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "".join(chunks)

    return llm_func
