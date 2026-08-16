"""Boundary 2：低分照实显示，不隐藏不夸大。"""
from graphkb.query import QueryResult
from graphkb.render import render

NAME = "b2_low_score_shown"
EXPECTATION = "Boundary 2: 低分照实显示，不隐藏不夸大"


async def run():
    result = QueryResult(
        question="q",
        answer="a",
        trace={"entities": [{"name": "X", "score": 0.01}], "relationships": []},
        trace_hit=True,
    )
    text = render(result)
    ok = "0.010" in text
    return ok, text.replace("\n", " | ")
