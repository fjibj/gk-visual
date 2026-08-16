"""Failure 1：删除不存在的文档 → 显式报错（非 success）。"""
from _common import run_with_rag

NAME = "f1_delete_nonexistent_reports"
EXPECTATION = "Failure 1: 删除不存在的文档必须显式报告，不静默"


async def run():
    async def body(rag):
        res = await rag.adelete_by_doc_id("不存在的文档")
        ok = res.status != "success"
        return ok, f"status={res.status} message={res.message}"

    return await run_with_rag(body)
