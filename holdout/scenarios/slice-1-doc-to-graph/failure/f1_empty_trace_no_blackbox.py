"""Failure 1：检索返回答案但 trace 为空 → 绝不悄悄返回黑盒答案（守卫返回"未找到"）。

用小假 rag 模拟"trace 机制坏掉但 aquery 编了个答案"：query() 必须挡掉编造答案。
"""
from graphkb.query import NOT_FOUND_ANSWER, query

NAME = "f1_empty_trace_no_blackbox"
EXPECTATION = "Failure 1: trace 为空时不返回黑盒答案（返回'未找到'）"


class _FakeRag:
    async def aquery_data(self, question, param):
        return {
            "status": "success",
            "message": "ok",
            "data": {"entities": [], "relationships": [], "chunks": []},
            "metadata": {},
        }

    async def aquery(self, question, param):
        return "这是凭空编造的答案"


async def run():
    r = await query(_FakeRag(), "问题", hl_keywords=["x"])
    passed = (r.answer == NOT_FOUND_ANSWER) and (r.trace_hit is False)
    return passed, f"answer={r.answer!r}"
