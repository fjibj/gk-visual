"""Failure 1：增量丢失（重建）必须被显式暴露，不静默。"""
from graphkb.ingest import ingest_document

NAME = "f1_rebuild_detected"
EXPECTATION = "Failure 1: 摄入后旧实体消失（重建）→ lost_entities 非空，显式暴露"


class _FakeGraph:
    def __init__(self):
        self.nodes = [{"entity_id": "张三"}]

    async def get_all_nodes(self):
        return self.nodes

    async def get_all_edges(self):
        return [{"source": "张三", "target": "字节跳动"}]


class _FakeRag:
    def __init__(self):
        self.chunk_entity_relation_graph = _FakeGraph()

    async def ainsert(self, text):
        # 模拟重建：旧图清空，只剩新实体
        self.chunk_entity_relation_graph.nodes = [{"entity_id": "李四"}]
        return "doc-2"


async def run():
    r = await ingest_document(_FakeRag(), "任意文本")
    ok = r.lost_entities == ["张三"]
    return ok, f"lost_entities={r.lost_entities}"
