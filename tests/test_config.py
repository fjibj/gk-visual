"""config.py 单元测试：环境变量解析 + （与 cwd 无关的）目录解析。"""

from __future__ import annotations

import os
from pathlib import Path

from graphkb.config import ENV_FILE, REPO_ROOT, load_config, resolve_dir


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


# ---------------------------------------------------------------- 与 cwd 无关


def test_working_dir_resolves_against_repo_root_not_cwd(monkeypatch):
    """stdio 的 MCP 客户端把 cwd 设成什么都可能（探针 A：Cola 用的是 `D:\\Cola`）。

    相对路径如果按 cwd 算，就会在那个目录下静静建一个新库——所以一律按仓库根解析。
    """
    monkeypatch.delenv("GKB_WORKING_DIR", raising=False)
    assert Path(load_config().working_dir) == (REPO_ROOT / "data").resolve()


def test_working_dir_relative_override_is_repo_root_based(monkeypatch):
    monkeypatch.setenv("GKB_WORKING_DIR", "data/sub")
    assert Path(load_config().working_dir) == (REPO_ROOT / "data" / "sub").resolve()


def test_working_dir_absolute_override_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("GKB_WORKING_DIR", str(tmp_path))
    assert Path(load_config().working_dir) == tmp_path
    assert resolve_dir(str(tmp_path)) == str(tmp_path)


def test_env_file_points_at_repo_root():
    """`.env` 只认仓库根那一份：从别的目录启动不该把密钥/地址丢在找不到的地方。"""
    assert ENV_FILE.parent == REPO_ROOT
    assert ENV_FILE.name == ".env"
