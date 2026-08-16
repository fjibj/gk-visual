"""共享 harness：S7 检索可视化考卷（TestClient + mock，全离线）。

测后端 /api/query 端点结构（前端图上高亮 + 多轮颜色靠浏览器人工 + vision 复核）。
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
    """构建 client（临时 working_dir），执行 fn(client) -> (passed, detail)。"""
    td = tempfile.TemporaryDirectory()
    try:
        with make_client(td.name) as client:
            result = fn(client)
        return result
    finally:
        td.cleanup()
