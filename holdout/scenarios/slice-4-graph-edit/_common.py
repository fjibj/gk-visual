"""共享 harness：S4 编辑落库考卷（mock LLM + mock embedding，完全离线）。

判卷通过 FastAPI TestClient 走 server 的编辑 API，断言"编辑后重读图生效"——
这正是 S4 验收点 3（落库可验证）。不依赖 Ollama / 火山网络。
"""

from __future__ import annotations

import tempfile

from fastapi.testclient import TestClient

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.server import create_app


def make_config(workdir):
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="mock", dim=64),
        working_dir=str(workdir),
    )


def make_client(workdir):
    return TestClient(create_app(config=make_config(workdir)))


def run_with_client(fn):
    """构建 client（临时 working_dir），执行同步 fn(client) -> (passed, detail)。"""
    td = tempfile.TemporaryDirectory()
    try:
        with make_client(td.name) as client:
            result = fn(client)
        return result
    finally:
        td.cleanup()
