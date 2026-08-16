"""Failure 2：trace 空 → 如实显示未命中，不画假路径。"""
from graphkb.query import QueryResult
from graphkb.render import render

NAME = "f2_empty_trace_shows_miss"
EXPECTATION = "Failure 2: trace 空时如实显示未命中，不画假命中路径"


async def run():
    result = QueryResult(question="q", answer="未找到相关实体。", trace={}, trace_hit=False)
    text = render(result)
    ok = "未命中" in text and "命中实体" not in text
    return ok, text.replace("\n", " | ")
