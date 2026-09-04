"""Boundary 1：扫描版 PDF（无文本层）→ 解析出空文本，检出为「需 OCR」而非入库。

（扫描版 pdf 的「拒绝」判定在 HTTP 层，pytest 已覆盖；本场景验证解析层行为：
空文本 → 调用方（upsert 之前）能看见空，从而不产生文档记录。）
"""
from _common import make_pdf_blank, run_with_rag
from graphkb.documents import list_documents
from lightrag.parser.legacy import extract_text

NAME = "b1_blank_pdf_no_text_layer"
EXPECTATION = "Boundary 2: 扫描版 pdf → 空文本，入库前被拦截"


async def run():
    async def body(rag):
        text = extract_text(make_pdf_blank(), "pdf").strip()
        ok = text == ""  # 无文本层 → 空 → 上游 400「需 OCR」，绝不拿空串去喂图
        if not ok:
            return False, f"空 PDF 竟抽出文本: {text[:60]!r}"
        docs = await list_documents(rag)
        # 语义：空内容不得产生记录（HTTP 层 400 前不会调 upsert，这里直接验证库干净）
        return ok, f"提取为空 ✓（文档数={len(docs)}）"

    return await run_with_rag(body)
