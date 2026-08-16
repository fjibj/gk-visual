"""Failure 1：分数拿不到（向量库异常）→ 如实标注无分数，不编造。"""
from graphkb.query import QueryResult, _score_trace
from graphkb.render import render

NAME = "f1_no_score_no_fabricate"
EXPECTATION = "Failure 1: 分数拿不到时如实标注无分数，不编造一个数字"


class _BoomVdb:
    async def query(self, question, top_k):
        raise RuntimeError("vdb down")


class _FakeRag:
    def __init__(self):
        self.entities_vdb = _BoomVdb()
        self.relationships_vdb = _BoomVdb()


async def run():
    trace = {
        "entities": [{"name": "字节跳动"}],
        "relationships": [{"src": "a", "tgt": "b"}],
    }
    out = await _score_trace(_FakeRag(), "q", trace)
    entity_score_none = out["entities"][0]["score"] is None

    result = QueryResult(question="q", answer="a", trace=out, trace_hit=True)
    text = render(result)
    shows_no_score = "无分数" in text

    return (entity_score_none and shows_no_score), text.replace("\n", " | ")
