"""Boundary 2：删除文档后，被其余文档支撑的共享实体保留。"""
from _common import SAMPLE1, SAMPLE2, run_with_rag
from graphkb.documents import upsert_document

NAME = "b2_shared_entity_preserved"
EXPECTATION = "Boundary 2: 共享实体（被多文档支撑）在删除其一后保留"


async def run():
    async def body(rag):
        await upsert_document(rag, "sample1", SAMPLE1)
        await upsert_document(rag, "sample2", SAMPLE2)
        await rag.adelete_by_doc_id("sample1")

        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = {n.get("entity_id") for n in nodes}
        # 北京被 sample1 和 sample2 共同提到 → 删除 sample1 后仍应保留
        ok = "北京" in names
        return ok, f"删除 sample1 后实体={sorted(names)}"

    return await run_with_rag(body)
