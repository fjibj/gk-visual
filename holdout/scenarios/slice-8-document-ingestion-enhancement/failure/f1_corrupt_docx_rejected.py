"""Failure 1：损坏的 .docx → 解析层必须抛错（不许静默解码成垃圾文本入库）。"""
from _common import run_with_rag
from graphkb.documents import list_documents
from lightrag.parser.legacy import extract_text

CORRUPT = b"PK\x03\x04 this is not a real zip archive at all........"

NAME = "f1_corrupt_docx_rejected"
EXPECTATION = "Failure 1: 损坏文件 → 解析报错，不产生任何实体/文档记录"


async def run():
    async def body(rag):
        raised = False
        error_kind = ""
        try:
            text = extract_text(CORRUPT, "docx")
        except Exception as exc:  # noqa: BLE001
            raised = True
            error_kind = type(exc).__name__
        if not raised:
            return False, f"损坏 docx 没抛错，反而返回了文本: {text[:40]!r}"
        docs = await list_documents(rag)
        ok = len(docs) == 0  # 解析失败发生在入库前 → 库是干净的
        return ok, f"解析抛出 {error_kind}，文档数={len(docs)}（应为 0）"

    return await run_with_rag(body)
