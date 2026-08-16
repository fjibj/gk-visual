"""Boundary 1：提问图中不存在的实体 → 如实未命中，返回'未找到'，不编造。"""
from _common import run_with_rag
from graphkb.query import NOT_FOUND_ANSWER, query

NAME = "b1_nonexistent_entity"
EXPECTATION = "Boundary 1: 图中不存在的实体 → 未命中 + '未找到'"


async def run():
    async def body(rag):
        # 空图（不注入任何数据），查任何实体都应未命中
        r = await query(rag, "李四在哪里？", hl_keywords=["李四"], ll_keywords=["李四"])
        passed = (r.trace_hit is False) and (r.answer == NOT_FOUND_ANSWER) and (r.trace["entities"] == [])
        return passed, f"trace_hit={r.trace_hit} answer={r.answer!r}"

    return await run_with_rag(None, body)
