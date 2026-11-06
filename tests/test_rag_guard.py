"""rag.py 的实例守卫：同进程里同 workspace、不同库目录，要喊出来（真图回归蹲到的坑）。"""

from __future__ import annotations

import logging

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.rag import _WORKSPACE_OWNER, build_rag


def _cfg(working_dir: str, workspace: str = "") -> Config:
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="mock", dim=8),
        working_dir=working_dir,
        workspace=workspace,
    )


def test_same_workspace_different_dir_warns(caplog):
    """LightRAG 的 KV 挂在进程级共享字典上：后开的实例 text_chunks 会是空的，必须先喊。"""
    _WORKSPACE_OWNER.clear()
    with caplog.at_level(logging.WARNING, logger="graphkb.rag"):
        build_rag(_cfg("C:/tmp/gkb_ws_a"))
        build_rag(_cfg("C:/tmp/gkb_ws_b"))
    assert any("workspace" in r.message and "空的 text_chunks" in r.message for r in caplog.records)


def test_same_workspace_same_dir_is_silent(caplog):
    """同一个库重复构建不算冲突：共享的就是同一份数据。"""
    _WORKSPACE_OWNER.clear()
    with caplog.at_level(logging.WARNING, logger="graphkb.rag"):
        build_rag(_cfg("C:/tmp/gkb_ws_same"))
        build_rag(_cfg("C:/tmp/gkb_ws_same"))
    assert not [r for r in caplog.records if r.name == "graphkb.rag"]


def test_different_workspace_is_silent(caplog):
    """不同 workspace 本身就是隔离的——回归里真库那条就是这么修的。"""
    _WORKSPACE_OWNER.clear()
    with caplog.at_level(logging.WARNING, logger="graphkb.rag"):
        build_rag(_cfg("C:/tmp/gkb_ws_c"))
        build_rag(_cfg("C:/tmp/gkb_ws_c", workspace="live"))
    assert not [r for r in caplog.records if r.name == "graphkb.rag"]
