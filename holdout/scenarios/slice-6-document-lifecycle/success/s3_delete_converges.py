"""Success 3：删除文档 → 独有实体消失。"""
from _common import SAMPLE1, SAMPLE2, run_with_rag
from graphkb.documents import upsert_document

NAME = "s3_delete_converges"
EXPECTATION = "Success 3: 删除文档后其独有实体消失"


async def run():
    async def body(rag):
        await upsert_document(rag, "sample1", SAMPLE1)
        await upsert_document(rag, "sample2", SAMPLE2)
        before = {n.get("entity_id") for n in await rag.chunk_entity_relation_graph.get_all_nodes()}

        await rag.adelete_by_doc_id("sample1")

        after = {n.get("entity_id") for n in await rag.chunk_entity_relation_graph.get_all_nodes()}
        # sample1 独有：张三、张一鸣（sample2 无）；消失即收敛
        ok = "张三" not in after and "张一鸣" not in after and len(after) < len(before)
        return ok, f"删除前={sorted(before)} 删除后={sorted(after)}"

    return await run_with_rag(body)
