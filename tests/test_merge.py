"""merge 封装测试：_FakeRag 锁定 amerge_entities 调用参数与返回键。"""

from __future__ import annotations

import asyncio

from graphkb.merge import merge_entities


class _FakeGraph:
    def __init__(self):
        self.edges = [
            {"source": "张三", "target": "字节跳动"},
            {"source": "李四", "target": "北京"},
        ]
        self.nodes = [
            {"entity_id": "张三"},
            {"entity_id": "李四"},
            {"entity_id": "北京"},
        ]

    async def get_all_edges(self):
        return self.edges

    async def get_all_nodes(self):
        return self.nodes


class _FakeRag:
    def __init__(self):
        self.chunk_entity_relation_graph = _FakeGraph()
        self.merge_calls = []

    async def amerge_entities(self, source_entities, target_entity):
        self.merge_calls.append((source_entities, target_entity))
        # 模拟 LightRAG 合并：李四→北京 转移到 张三→北京，且删除李四节点
        self.chunk_entity_relation_graph.edges = [
            {"source": "张三", "target": "字节跳动"},
            {"source": "张三", "target": "北京"},
        ]
        self.chunk_entity_relation_graph.nodes = [
            {"entity_id": "张三"},
            {"entity_id": "北京"},
        ]
        return {
            "entity_name": target_entity,
            "source_id": "src",
            "graph_data": {"entity_id": target_entity, "entity_type": "person"},
        }


class _LeakyRag(_FakeRag):
    async def amerge_entities(self, source_entities, target_entity):
        self.merge_calls.append((source_entities, target_entity))
        # 模拟半合并：源实体李四未删除（nodes 保持不动）
        self.chunk_entity_relation_graph.edges = [
            {"source": "张三", "target": "字节跳动"},
            {"source": "张三", "target": "北京"},
        ]
        return {
            "entity_name": target_entity,
            "source_id": "src",
            "graph_data": {"entity_id": target_entity},
        }


def test_merge_entities_result_and_call():
    rag = _FakeRag()
    result = asyncio.run(merge_entities(rag, ["李四"], "张三"))

    assert rag.merge_calls == [(["李四"], "张三")]
    assert result.target_entity == "张三"
    assert result.deleted_entities == ["李四"]
    assert result.relationships_transferred == 1
    assert result.target_final.get("entity_type") == "person"
    assert result.sources_remaining == []


def test_merge_sources_remaining_detected():
    """模拟半合并（源未删）→ sources_remaining 应非空，显式暴露。"""
    rag = _LeakyRag()
    result = asyncio.run(merge_entities(rag, ["李四"], "张三"))
    assert result.sources_remaining == ["李四"]
