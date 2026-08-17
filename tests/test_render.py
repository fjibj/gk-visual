"""S3 测试：_hit_trace 命中收敛 + 分数映射 + render 渲染输出（纯函数，确定性）。"""

from __future__ import annotations

import asyncio

from graphkb.query import QueryResult, _safe_score, _hit_trace
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


def test_hit_trace_core_plus_graph_spread():
    rag = _FakeRag(
        entities_vdb=_FakeVdb(
            [
                {"entity_name": "张三", "distance": 0.539},
                {"entity_name": "软件工程师", "distance": 0.459},
            ]
        ),
    )
    trace = {
        "keywords": {"high_level": ["工作地点"], "low_level": ["张三"]},
        "entities": [
            {"name": "张三", "type": "person", "description": "员工"},
            {"name": "字节跳动", "type": "organization", "description": "公司"},
            {"name": "北京", "type": "location", "description": "城市"},
            {"name": "李雷", "type": "person", "description": "无关"},
        ],
        "relationships": [
            {"src": "字节跳动", "tgt": "张三", "description": "雇佣", "keywords": "", "weight": 1.0},
            {"src": "北京", "tgt": "张三", "description": "工作地", "keywords": "", "weight": 1.0},
            {"src": "李雷", "tgt": "腾讯", "description": "无关边", "keywords": "", "weight": 1.0},
        ],
    }
    out = asyncio.run(_hit_trace(rag, "张三在哪工作", trace))

    # 核心实体（ll_keywords 检索 top_k）+ 图扩散带出邻居端点；独立分量被排除
    names = {e["name"] for e in out["entities"]}
    assert "张三" in names and "字节跳动" in names and "北京" in names
    assert "李雷" not in names
    # 关系只含与核心实体相连的边
    rel_keys = {f"{r['src']}->{r['tgt']}" for r in out["relationships"]}
    assert "字节跳动->张三" in rel_keys
    assert "李雷->腾讯" not in rel_keys
    # 核心实体有 score
    zhang = next(e for e in out["entities"] if e["name"] == "张三")
    assert zhang["score"] == 0.539


def test_hit_trace_degraded_on_error():
    rag = _FakeRag(entities_vdb=_BoomVdb())
    trace = {
        "keywords": {"low_level": ["张三"]},
        "entities": [{"name": "字节跳动"}],
        "relationships": [{"src": "字节跳动", "tgt": "张一鸣"}],
    }
    out = asyncio.run(_hit_trace(rag, "q", trace))
    # 降级：保留原集合，score 为 None
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
