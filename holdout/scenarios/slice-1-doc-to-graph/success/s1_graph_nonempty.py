"""Success 1：喂含多实体/关系的图 → 实体数>0 且关系数>0。"""
from _common import KG, run_with_rag

NAME = "s1_graph_nonempty"
EXPECTATION = "Success 1: 建图后实体数>0 且关系数>0"


async def run():
    async def body(rag):
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        n, e = len(nodes), len(edges)
        return (n > 0 and e > 0), f"entities={n} relations={e}"

    return await run_with_rag(KG, body)
