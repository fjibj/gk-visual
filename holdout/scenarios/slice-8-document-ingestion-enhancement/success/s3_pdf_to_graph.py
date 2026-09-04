"""Success 3：上传文本型 .pdf → 解析出可读文本（无乱码）→ 图长出。"""
from _common import PDF_TEXT, make_pdf, run_with_rag
from graphkb.documents import list_documents, upsert_document
from lightrag.parser.legacy import extract_text

NAME = "s3_pdf_to_graph"
EXPECTATION = "Success 2: 文本型 pdf → 图长出，无乱码"


async def run():
    async def body(rag):
        text = extract_text(make_pdf(), "pdf")
        if "Alice" not in text or "Acme" not in text:
            return False, f"PDF 解析乱码或缺内容: {text[:80]!r}"
        r = await upsert_document(rag, "pdf导入测试", text)
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = {n.get("entity_id") for n in nodes}
        docs = await list_documents(rag)
        ok = r.entity_count > 0 and any(x in names for x in ("Alice", "Acme", "Boston"))
        detail = f"entity_count={r.entity_count} 实体={sorted(names)} 文档数={len(docs)}"
        return ok, detail

    return await run_with_rag(body)
