"""Success 4：覆盖更新（同标题重传）→ 仍是同一篇、created=False。"""
from _common import SAMPLE1, SAMPLE1_V2, run_with_rag
from graphkb.documents import list_documents, upsert_document

NAME = "s4_overwrite_updates"
EXPECTATION = "Success 4: 同标题重传 = 覆盖更新，文档仍是一篇"


async def run():
    async def body(rag):
        await upsert_document(rag, "sample1", SAMPLE1)
        r = await upsert_document(rag, "sample1", SAMPLE1_V2)
        docs = await list_documents(rag)
        ids = {d.doc_id for d in docs}
        ok = r.created is False and len(ids) == 1
        return ok, f"created={r.created} 文档数={len(ids)}"

    return await run_with_rag(body)
