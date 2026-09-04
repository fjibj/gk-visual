"""Success 1：上传 .docx → 解析出纯文本 → 图长出实体。"""
from _common import DOCX_TEXT, make_docx, run_with_rag
from graphkb.documents import list_documents, upsert_document
from lightrag.parser.legacy import extract_text

NAME = "s1_docx_to_graph"
EXPECTATION = "Success 1: docx → 图长出实体，文档列表出现该文档"


async def run():
    async def body(rag):
        text = extract_text(make_docx(), "docx")
        if "字节跳动" not in text:
            return False, f"解析结果缺关键内容: {text[:80]!r}"
        r = await upsert_document(rag, "docx导入测试", text)
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = {n.get("entity_id") for n in nodes}
        docs = await list_documents(rag)
        ok = r.entity_count > 0 and any("字节跳动" in n for n in names)
        detail = f"entity_count={r.entity_count} 实体={sorted(names)} 文档数={len(docs)}"
        return ok, detail

    return await run_with_rag(body)
