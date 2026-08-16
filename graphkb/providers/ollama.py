"""本地 Ollama provider（LLM + embedding）。"""

from __future__ import annotations

import httpx
import numpy as np
from lightrag.utils import EmbeddingFunc

from ..config import EmbeddingConfig, LLMConfig


def make_ollama_llm(cfg: LLMConfig):
    base_url = cfg.base_url.rstrip("/")
    model = cfg.model

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

        payload = {"model": model, "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["message"]["content"]

    return llm_func


def make_ollama_embedding(cfg: EmbeddingConfig):
    base_url = cfg.base_url.rstrip("/")
    model = cfg.model

    async def _embed(texts: list[str]) -> np.ndarray:
        payload = {"model": model, "input": list(texts)}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            resp = await client.post(f"{base_url}/api/embed", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return np.array(data["embeddings"], dtype=np.float32)

    return EmbeddingFunc(
        embedding_dim=cfg.dim,
        max_token_size=cfg.max_token_size,
        func=_embed,
        model_name=model,
    )
