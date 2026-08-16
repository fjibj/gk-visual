"""Failure 2：半合并（源未删）必须被显式暴露，不静默。"""
from graphkb.merge import merge_entities

NAME = "f2_half_merge_detected"
EXPECTATION = "Failure 2: 合并后源实体残留（半合并）→ sources_remaining 非空，显式暴露"


class _FakeGraph:
    def __init__(self):
        self.edges = [{"source": "张三", "target": "字节跳动"}]
        self.nodes = [{"entity_id": "张三"}, {"entity_id": "字节跳动"}]

    async def get_all_edges(self):
        return self.edges

    async def get_all_nodes(self):
        return self.nodes


class _FakeRag:
    def __init__(self):
        self.chunk_entity_relation_graph = _FakeGraph()

    async def amerge_entities(self, source_entities, target_entity):
        # 模拟半合并：不删除源（nodes 保持不动，张三仍在）
        return {"entity_name": target_entity, "source_id": "s", "graph_data": {}}


async def run():
    r = await merge_entities(_FakeRag(), ["张三"], "字节跳动")
    ok = r.sources_remaining == ["张三"]
    return ok, f"sources_remaining={r.sources_remaining}"
