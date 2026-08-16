"""Boundary 1：空内容文档 → 被拒绝，不崩溃。"""
from _common import run_with_rag
from graphkb.documents import upsert_document

NAME = "b1_empty_content_rejected"
EXPECTATION = "Boundary 1: 空内容文档被拒绝"


async def run():
    async def body(rag):
        try:
            await upsert_document(rag, "empty", "   ")
            return False, "空内容未被拒绝"
        except ValueError as exc:
            return True, f"空内容被拒绝: {exc}"

    return await run_with_rag(body)
