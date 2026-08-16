"""Success 1：上传文档 → 图长出（实体出现）。"""
from _common import SAMPLE1, run_with_rag
from graphkb.documents import upsert_document

NAME = "s1_upload_grows_graph"
EXPECTATION = "Success 1: 上传文档后图长出实体"


async def run():
    async def body(rag):
        r = await upsert_document(rag, "sample1", SAMPLE1)
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = {n.get("entity_id") for n in nodes}
        ok = r.entity_count > 0 and "张三" in names
        return ok, f"entity_count={r.entity_count} 实体={sorted(names)}"

    return await run_with_rag(body)
