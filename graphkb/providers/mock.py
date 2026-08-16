"""确定性 mock provider，供离线测试 / 无外部依赖时跑通骨架。

mock embedding：对文本做 sha256 得到种子，生成归一化随机向量（同文本→同向量，可复现）。
"""

from __future__ import annotations

import hashlib

import numpy as np
from lightrag.utils import EmbeddingFunc

from ..config import EmbeddingConfig, LLMConfig


def make_mock_llm(cfg: LLMConfig):
    async def llm_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        keyword_extraction=False,
        **kwargs,
    ) -> str:
        return "mock-response"

    return llm_func


def make_mock_embedding(cfg: EmbeddingConfig):
    dim = cfg.dim

    async def _embed(texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big")
            v = np.random.default_rng(seed).standard_normal(dim).astype(np.float32)
            out[i] = v / (np.linalg.norm(v) + 1e-8)
        return out

    return EmbeddingFunc(
        embedding_dim=dim,
        max_token_size=cfg.max_token_size,
        func=_embed,
        model_name="mock",
    )
