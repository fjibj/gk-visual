"""config.py 单元测试：环境变量解析。"""

from __future__ import annotations

import os

from graphkb.config import load_config


def test_load_config_defaults(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GKB_"):
            monkeypatch.delenv(k)
    cfg = load_config()
    assert cfg.llm.provider == "anthropic"
    assert cfg.embedding.provider == "ollama"
    assert cfg.embedding.dim == 1024


def test_load_config_env_override(monkeypatch):
    monkeypatch.setenv("GKB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("GKB_LLM_MODEL", "mock-model")
    monkeypatch.setenv("GKB_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("GKB_EMBEDDING_DIM", "64")
    cfg = load_config()
    assert cfg.llm.provider == "mock"
    assert cfg.llm.model == "mock-model"
    assert cfg.embedding.provider == "mock"
    assert cfg.embedding.dim == 64


def test_load_config_retrieval_defaults(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GKB_"):
            monkeypatch.delenv(k)
    cfg = load_config()
    assert cfg.retrieval.hit_top_k == 5
    assert cfg.retrieval.max_hops == 4
    assert cfg.retrieval.max_paths == 6


def test_load_config_retrieval_env_override(monkeypatch):
    monkeypatch.setenv("GKB_HIT_TOP_K", "3")
    monkeypatch.setenv("GKB_MAX_HOPS", "1")
    monkeypatch.setenv("GKB_MAX_PATHS", "2")
    cfg = load_config()
    assert (cfg.retrieval.hit_top_k, cfg.retrieval.max_hops, cfg.retrieval.max_paths) == (3, 1, 2)
