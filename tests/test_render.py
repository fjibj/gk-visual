"""S3 测试：_score_trace 分数映射 + render 渲染输出（纯函数，确定性）。"""

from __future__ import annotations

import asyncio

from graphkb.query import QueryResult, _safe_score, _score_trace
from graphkb.render import render


def test_safe_score():
    assert _safe_score(0.5) == 0.5
    assert _safe_score("0.8") == 0.8
    assert _safe_score(None) is None
    assert _safe_score("bad") is None


class _FakeVdb:
    def __init__(self, results):
        self._results = results

    async def query(self, question, top_k):
        return self._results


class _BoomVdb:
    async def query(self, question, top_k):
        raise RuntimeError("vdb down")


class _FakeRag:
    def __init__(self, entities_vdb=None, relationships_vdb=None):
        self.entities_vdb = entities_vdb or _FakeVdb([])
        self.relationships_vdb = relationships_vdb or _FakeVdb([])


def test_score_trace_maps_entities_and_relations():
    rag = _FakeRag(
        entities_vdb=_FakeVdb(
            [
                {"entity_name": "字节跳动", "distance": 0.803},
                {"entity_name": "张三", "distance": 0.30},
            ]
        ),
        relationships_vdb=_FakeVdb(
            [{"src_id": "张一鸣", "tgt_id": "字节跳动", "distance": 0.67}]
        ),
    )
    trace = {
        "entities": [{"name": "字节跳动"}, {"name": "张三"}],
        "relationships": [{"src": "字节跳动", "tgt": "张一鸣"}],
    }
    out = asyncio.run(_score_trace(rag, "q", trace))

    assert out["entities"][0]["score"] == 0.803
    assert out["entities"][1]["score"] == 0.30
    # 关系用 sorted(src,tgt) 做 key：字节跳动↔张一鸣 两方向命中同一条
    assert out["relationships"][0]["score"] == 0.67


def test_score_trace_degraded_on_error():
    rag = _FakeRag(entities_vdb=_BoomVdb(), relationships_vdb=_BoomVdb())
    trace = {
        "entities": [{"name": "字节跳动"}],
        "relationships": [{"src": "字节跳动", "tgt": "张一鸣"}],
    }
    out = asyncio.run(_score_trace(rag, "q", trace))
    assert out["entities"][0]["score"] is None
    assert out["relationships"][0]["score"] is None


def test_render_hit():
    result = QueryResult(
        question="谁创立了字节跳动？",
        answer="张一鸣",
        trace={
            "keywords": {"high_level": ["创始人"], "low_level": ["字节跳动"]},
            "entities": [{"name": "字节跳动", "type": "organization", "score": 0.8}],
            "relationships": [{"src": "字节跳动", "tgt": "张一鸣", "score": 0.67}],
            "chunks": [{"content": "字节跳动由张一鸣创立。"}],
        },
        trace_hit=True,
    )
    text = render(result)
    assert "字节跳动" in text
    assert "张一鸣" in text
    assert "0.800" in text


def test_render_miss():
    result = QueryResult(question="q", answer="未找到相关实体。", trace={}, trace_hit=False)
    text = render(result)
    assert "未命中" in text


def test_render_no_score():
    result = QueryResult(
        question="q",
        answer="a",
        trace={"entities": [{"name": "X", "score": None}], "relationships": []},
        trace_hit=True,
    )
    text = render(result)
    assert "无分数" in text
