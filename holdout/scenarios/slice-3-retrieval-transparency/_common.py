"""共享 harness：S3 确定性考卷环境（mock LLM + 真实 bge-m3 embedding）。"""

from __future__ import annotations

import tempfile

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.rag import init_rag

KG = {
    "chunks": [{"content": "张三在字节跳动工作，字节跳动总部位于北京。", "source_id": "c1"}],
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "工程师", "source_id": "c1"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "c1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "c1"},
    ],
    "relationships": [
        {"src_id": "张三", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0, "source_id": "c1"},
        {"src_id": "字节跳动", "tgt_id": "北京", "description": "总部位于", "keywords": "位于", "weight": 1.0, "source_id": "c1"},
    ],
}


def make_config(workdir):
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(
            provider="ollama", model="bge-m3", dim=1024, base_url="http://localhost:11434"
        ),
        working_dir=str(workdir),
    )


async def build_rag(workdir, kgs=None):
    rag = await init_rag(make_config(workdir))
    for kg in kgs or []:
        await rag.ainsert_custom_kg(kg)
    if kgs:
        # flush 向量库，让 entities_vdb.query / relationships_vdb.query 可见
        await rag.entities_vdb.index_done_callback()
        await rag.relationships_vdb.index_done_callback()
    return rag


async def run_with_rag(kg, fn):
    """构建 rag，注入 kg（dict 或 list[dict]），执行 fn(rag) -> (passed, detail)。"""
    td = tempfile.TemporaryDirectory()
    try:
        kgs = kg if isinstance(kg, list) else ([kg] if kg is not None else [])
        rag = await build_rag(td.name, kgs)
        result = await fn(rag)
        await rag.finalize_storages()
        return result
    finally:
        td.cleanup()
