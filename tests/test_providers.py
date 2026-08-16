"""providers 单元测试：工厂 + mock 确定性。"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.providers import build_embedding, build_llm


def test_mock_llm_returns_string():
    llm = build_llm(Config(llm=LLMConfig(provider="mock")))
    out = asyncio.run(llm("hi"))
    assert isinstance(out, str)
    assert out == "mock-response"


def test_mock_embedding_shape_and_determinism():
    emb = build_embedding(Config(embedding=EmbeddingConfig(provider="mock", dim=64)))
    v1 = asyncio.run(emb(["你好"]))
    v2 = asyncio.run(emb(["你好"]))
    assert v1.shape == (1, 64)
    assert np.array_equal(v1, v2)


def test_mock_embedding_distinguishes_text():
    emb = build_embedding(Config(embedding=EmbeddingConfig(provider="mock", dim=64)))
    v1 = asyncio.run(emb(["你好"]))
    v3 = asyncio.run(emb(["世界"]))
    assert not np.array_equal(v1, v3)


def test_unknown_llm_provider_raises():
    with pytest.raises(ValueError):
        build_llm(Config(llm=LLMConfig(provider="nope")))


def test_unknown_embedding_provider_raises():
    with pytest.raises(ValueError):
        build_embedding(Config(embedding=EmbeddingConfig(provider="nope")))
