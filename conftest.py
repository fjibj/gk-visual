"""pytest 根 conftest：让 graphkb 可导入，并提供 mock 配置 fixture。"""

from __future__ import annotations

import pytest

from graphkb.config import Config, EmbeddingConfig, LLMConfig


@pytest.fixture
def mock_config(tmp_path) -> Config:
    """全 mock 配置（确定性，无外部依赖）。"""
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="mock", dim=64),
        working_dir=str(tmp_path / "data"),
    )
