"""Boundary 2：同一实体反复提及 → 不出现大量重复节点。"""
from _common import run_with_rag

NAME = "b2_repeated_entity_no_dupes"
EXPECTATION = "Boundary 2: 同一实体反复提及不产生重复节点"

DUP_KG = {
    "chunks": [{"content": "张三在北京。张三在上海。", "source_id": "chunk-1"}],
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "第一次提及", "source_id": "chunk-1"},
        {"entity_name": "张三", "entity_type": "person", "description": "第二次提及", "source_id": "chunk-1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "chunk-1"},
    ],
    "relationships": [],
}


async def run():
    async def body(rag):
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        zhangsan = [n for n in nodes if n.get("entity_id") == "张三"]
        return (len(zhangsan) == 1), f"张三节点数={len(zhangsan)} 总节点数={len(nodes)}"

    return await run_with_rag(DUP_KG, body)
