"""Success 2：列出文档（含贡献实体/关系数）。"""
from _common import SAMPLE1, SAMPLE2, run_with_rag
from graphkb.documents import list_documents, upsert_document

NAME = "s2_list_shows_documents"
EXPECTATION = "Success 2: 文档列表返回两篇文档及各自贡献数"


async def run():
    async def body(rag):
        await upsert_document(rag, "sample1", SAMPLE1)
        await upsert_document(rag, "sample2", SAMPLE2)
        docs = await list_documents(rag)
        ids = {d.doc_id for d in docs}
        has_counts = all(d.entity_count >= 0 and d.relation_count >= 0 for d in docs)
        ok = len(ids) == 2 and "sample1" in ids and "sample2" in ids and has_counts
        return ok, f"文档={sorted(ids)} 详情={[(d.doc_id, d.entity_count) for d in docs]}"

    return await run_with_rag(body)
