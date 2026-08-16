"""共享 harness：S2 确定性考卷环境（mock LLM + 真实 bge-m3 embedding）。

注意：与 S1 一致，embedding 走真实 bge-m3（确定性向量），LLM 用 mock（不参与图注入）。
考卷依赖本地 Ollama 已运行（http://localhost:11434）。
"""

from __future__ import annotations

import tempfile

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.rag import init_rag

BATCH_A = {
    "chunks": [{"content": "张三在字节跳动工作。", "source_id": "ca1"}],
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "工程师", "source_id": "ca1"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "ca1"},
    ],
    "relationships": [
        {"src_id": "张三", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0, "source_id": "ca1"},
    ],
}

BATCH_B_disjoint = {
    "chunks": [{"content": "李四在北京居住。", "source_id": "cb1"}],
    "entities": [
        {"entity_name": "李四", "entity_type": "person", "description": "产品经理", "source_id": "cb1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "cb1"},
    ],
    "relationships": [
        {"src_id": "李四", "tgt_id": "北京", "description": "居住于", "keywords": "居住", "weight": 1.0, "source_id": "cb1"},
    ],
}

BATCH_C_overlap = {
    "chunks": [{"content": "李四在字节跳动做产品经理，字节跳动总部在北京。", "source_id": "cc1"}],
    "entities": [
        {"entity_name": "李四", "entity_type": "person", "description": "产品经理", "source_id": "cc1"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "cc1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "cc1"},
    ],
    "relationships": [
        {"src_id": "李四", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0, "source_id": "cc1"},
        {"src_id": "字节跳动", "tgt_id": "北京", "description": "总部位于", "keywords": "位于", "weight": 1.0, "source_id": "cc1"},
    ],
}

MERGE_KG = {
    "chunks": [{"content": "字节跳动（ByteDance）总部位于北京。", "source_id": "cm1"}],
    "entities": [
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "cm1"},
        {"entity_name": "ByteDance", "entity_type": "organization", "description": "字节跳动的英文名", "source_id": "cm1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "cm1"},
    ],
    "relationships": [
        {"src_id": "ByteDance", "tgt_id": "北京", "description": "总部位于", "keywords": "位于", "weight": 1.0, "source_id": "cm1"},
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


async def entity_names(rag) -> list[str]:
    nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
    return [str(n.get("entity_id") or n.get("id") or n) for n in nodes]
