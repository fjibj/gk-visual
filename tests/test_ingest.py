"""ingest 集成测试：insert_custom_kg 注入已知图 + 计数（确定性）。"""

from __future__ import annotations

import asyncio

from graphkb.ingest import ingest_document
from graphkb.rag import init_rag

KG = {
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "软件工程师"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司"},
    ],
    "relationships": [
        {"src_id": "张三", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0},
    ],
}


def test_insert_custom_kg_counts(mock_config):
    async def run():
        rag = await init_rag(mock_config)
        await rag.ainsert_custom_kg(KG)
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        await rag.finalize_storages()
        return len(nodes), len(edges)

    n, e = asyncio.run(run())
    assert n == 2
    assert e == 1


class _FakeGraph:
    async def get_all_nodes(self):
        return [{"entity_id": "张三", "entity_type": "person"}]

    async def get_all_edges(self):
        return [{"source": "张三", "target": "字节跳动"}]


class _FakeRag:
    def __init__(self):
        self.chunk_entity_relation_graph = _FakeGraph()

    async def ainsert(self, text):
        return "doc-1"


def test_ingest_document_extraction_keys():
    """锁定图节点/边的真实键名（entity_id / source / target），防止回归。"""
    result = asyncio.run(ingest_document(_FakeRag(), "任意文本"))
    assert result.entity_count == 1
    assert result.relation_count == 1
    assert result.entities == ["张三"]
    assert result.relations == [("张三", "字节跳动")]
