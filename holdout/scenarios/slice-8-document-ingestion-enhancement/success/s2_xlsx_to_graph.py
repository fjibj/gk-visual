"""Success 2：上传 .xlsx → 单元格文本进图（表格内容被保留为文本）。"""
from _common import XLSX_TEXT, make_xlsx, run_with_rag
from graphkb.documents import list_documents, upsert_document
from lightrag.parser.legacy import extract_text

NAME = "s2_xlsx_to_graph"
EXPECTATION = "Success 3: xlsx → 单元格文本被解析进图"


async def run():
    async def body(rag):
        text = extract_text(make_xlsx([XLSX_TEXT]), "xlsx")
        if "字节跳动" not in text:
            return False, f"解析结果缺表格内容: {text[:80]!r}"
        r = await upsert_document(rag, "xlsx导入测试", text)
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = {n.get("entity_id") for n in nodes}
        docs = await list_documents(rag)
        ok = r.entity_count > 0 and "李四" in names
        detail = f"entity_count={r.entity_count} 实体={sorted(names)} 文档数={len(docs)}"
        return ok, detail

    return await run_with_rag(body)
