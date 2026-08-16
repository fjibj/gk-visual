"""Success 2：提问能被图中实体回答 → 返回答案且可溯源（trace_hit=True）。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "s2_answer_traceable"
EXPECTATION = "Success 2: 返回答案，且答案有 trace 背书（trace_hit=True，非凭空）"


async def run():
    async def body(rag):
        r = await query(rag, "张三在哪里工作？", hl_keywords=["张三"], ll_keywords=["张三"])
        passed = bool(r.answer) and r.trace_hit is True
        return passed, f"answer={r.answer!r} trace_hit={r.trace_hit}"

    return await run_with_rag(KG, body)
