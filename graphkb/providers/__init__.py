"""Provider 工厂：把配置映射成 LightRAG 可注入的 llm_model_func / embedding_func。"""

from __future__ import annotations

from ..config import Config
from .anthropic import make_anthropic_llm
from .mock import make_mock_embedding, make_mock_llm
from .ollama import make_ollama_embedding, make_ollama_llm
from .openai_compat import make_openai_embedding, make_openai_llm


def build_llm(config: Config):
    p = config.llm.provider
    if p == "anthropic":
        return make_anthropic_llm(config.llm)
    if p == "openai_compat":
        return make_openai_llm(config.llm)
    if p == "ollama":
        return make_ollama_llm(config.llm)
    if p == "mock":
        return make_mock_llm(config.llm)
    raise ValueError(f"未知 LLM provider: {p!r}")


def build_embedding(config: Config):
    p = config.embedding.provider
    if p == "openai_compat":
        return make_openai_embedding(config.embedding)
    if p == "ollama":
        return make_ollama_embedding(config.embedding)
    if p == "mock":
        return make_mock_embedding(config.embedding)
    raise ValueError(f"未知 embedding provider: {p!r}")
