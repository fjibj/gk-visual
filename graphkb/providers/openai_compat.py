"""OpenAI 兼容 provider（LLM + embedding），覆盖 OpenAI/DeepSeek/Kimi/通义/vLLM/LiteLLM 等。"""

from __future__ import annotations

import httpx
import numpy as np
from lightrag.utils import EmbeddingFunc

from ..config import EmbeddingConfig, LLMConfig


def make_openai_llm(cfg: LLMConfig):
    base_url = cfg.base_url.rstrip("/")
    model = cfg.model
    api_key = cfg.api_key

    async def llm_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        keyword_extraction=False,
        **kwargs,
    ) -> str:
        messages = []
        for m in history_messages or []:
            messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    return llm_func


def make_openai_embedding(cfg: EmbeddingConfig):
    base_url = cfg.base_url.rstrip("/")
    model = cfg.model
    api_key = cfg.api_key

    async def _embed(texts: list[str]) -> np.ndarray:
        payload = {"model": model, "input": list(texts)}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            resp = await client.post(f"{base_url}/embeddings", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        rows = sorted(data["data"], key=lambda x: x["index"])
        return np.array([r["embedding"] for r in rows], dtype=np.float32)

    return EmbeddingFunc(
        embedding_dim=cfg.dim,
        max_token_size=cfg.max_token_size,
        func=_embed,
        model_name=model,
    )
