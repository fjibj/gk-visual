"""pytest 根 conftest：让 graphkb 可导入，并提供 mock 配置 fixture。"""

from __future__ import annotations

import tempfile

import pytest

from graphkb.config import Config, EmbeddingConfig, LLMConfig


@pytest.fixture
def mock_config() -> Config:
    """全 mock 配置（确定性，无外部依赖）。

    working_dir 用 tempfile.mkdtemp（不经 pytest tmp_path），避免 Windows 沙箱下
    pytest 清理 tmp 目录时的 rmtree PermissionError。
    """
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="mock", dim=64),
        working_dir=tempfile.mkdtemp(prefix="gkb_test_"),
    )
