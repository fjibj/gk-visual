"""共享 harness：S5 编辑回路考卷（mock LLM + 真实 bge-m3 + 显式 hl_keywords）。

复用 S1 模式：ainsert_custom_kg 注入确定性 KG；编辑用 LightRAG 编辑 API；
检索用 graphkb.query.query（显式 hl_keywords 跳过 LLM 关键词抽取）。
考卷依赖本地 Ollama（bge-m3），因实体召回是向量语义检索。
"""

from __future__ import annotations

import tempfile

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.query import query
from graphkb.rag import init_rag

KG = {
    "chunks": [{"content": "张三在字节跳动工作，字节跳动总部位于北京。", "source_id": "chunk-1"}],
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "软件工程师", "source_id": "chunk-1"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "chunk-1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "chunk-1"},
    ],
    "relationships": [
        {"src_id": "张三", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0, "source_id": "chunk-1"},
        {"src_id": "字节跳动", "tgt_id": "北京", "description": "总部位于", "keywords": "位于", "weight": 1.0, "source_id": "chunk-1"},
    ],
}


def make_config(workdir):
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="ollama", model="bge-m3", dim=1024, base_url="http://localhost:11434"),
        working_dir=str(workdir),
    )


async def build_rag(workdir, kg=None):
    rag = await init_rag(make_config(workdir))
    if kg is not None:
        await rag.ainsert_custom_kg(kg)
    return rag


async def run_with_rag(kg, fn):
    """构建 rag（注入 kg），执行 fn(rag) -> (passed, detail)，自动清理临时目录。"""
    td = tempfile.TemporaryDirectory()
    try:
        rag = await build_rag(td.name, kg)
        result = await fn(rag)
        await rag.finalize_storages()
        return result
    finally:
        td.cleanup()
