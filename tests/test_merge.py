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

    async def get_all_edges(self):
        return self.edges


class _FakeRag:
    def __init__(self):
        self.chunk_entity_relation_graph = _FakeGraph()
        self.merge_calls = []

    async def amerge_entities(self, source_entities, target_entity):
        self.merge_calls.append((source_entities, target_entity))
        # 模拟 LightRAG 合并：李四→北京 转移到 张三→北京
        self.chunk_entity_relation_graph.edges = [
            {"source": "张三", "target": "字节跳动"},
            {"source": "张三", "target": "北京"},
        ]
        return {
            "entity_name": target_entity,
            "source_id": "src",
            "graph_data": {"entity_id": target_entity, "entity_type": "person"},
        }


def test_merge_entities_result_and_call():
    rag = _FakeRag()
    result = asyncio.run(merge_entities(rag, ["李四"], "张三"))

    assert rag.merge_calls == [(["李四"], "张三")]
    assert result.target_entity == "张三"
    assert result.deleted_entities == ["李四"]
    assert result.relationships_transferred == 1
    assert result.target_final.get("entity_type") == "person"
