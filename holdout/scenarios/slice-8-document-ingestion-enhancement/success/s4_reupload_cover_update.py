"""Success 4：同标题文件重传 = 覆盖更新（复用 S6 doc_id 身份）。"""
from _common import make_docx, run_with_rag
from graphkb.documents import list_documents, upsert_document
from lightrag.parser.legacy import extract_text

V1 = "王五是一位建筑师，他住在上海。王五在建筑设计院工作。"
V2 = "王五是一位建筑师，他住在杭州。"

NAME = "s4_reupload_cover_update"
EXPECTATION = "Success 4: 同标题 .docx 重传 → 覆盖更新，旧版收敛"


async def run():
    async def body(rag):
        t1 = extract_text(make_docx(V1), "docx")
        r1 = await upsert_document(rag, "覆盖测试文档", t1)
        docs_before = await list_documents(rag)

        t2 = extract_text(make_docx(V2), "docx")
        r2 = await upsert_document(rag, "覆盖测试文档", t2)
        docs_after = await list_documents(rag)

        ok = (
            r1.created is True
            and r2.created is False  # 同 doc_id → 覆盖而非新增
            and len(docs_after) == len(docs_before) == 1  # 不产生第二份记录
            and docs_after[0].content_length < docs_before[0].content_length  # 内容已换成 V2
        )
        detail = (
            f"r1.created={r1.created} r2.created={r2.created} "
            f"len_v1={docs_before[0].content_length} len_v2={docs_after[0].content_length}"
        )
        return ok, detail

    return await run_with_rag(body)
