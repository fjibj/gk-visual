"""query.py 单元测试：trace 构建 + 双文本判据在 query() 上的透传（纯函数，不联网）。"""

from __future__ import annotations

import asyncio

import pytest

from graphkb.query import _build_trace, query


def test_build_trace_empty():
    t = _build_trace({}, {})
    assert t["entities"] == []
    assert t["relationships"] == []
    assert t["chunks"] == []


def test_build_trace_records_raw_retrieval():
    """retrieved 记下检索器捞到的全部，后面怎么分层都不动它。"""
    data = {
        "entities": [{"entity_name": "张三"}, {"entity_name": "北京"}],
        "relationships": [{"src_id": "北京", "tgt_id": "张三"}],
        "chunks": [],
    }
    t = _build_trace(data, {})
    assert t["retrieved"]["entity_count"] == 2
    assert t["retrieved"]["entities"] == ["张三", "北京"]
    assert t["retrieved"]["relationships"] == ["北京->张三"]


def test_build_trace_shapes():
    data = {
        "entities": [{"entity_name": "张三", "entity_type": "person", "description": "x"}],
        "relationships": [
            {"src_id": "张三", "tgt_id": "字节跳动", "description": "y", "keywords": "任职", "weight": 1.0}
        ],
        "chunks": [{"content": "z", "chunk_id": "c1"}],
    }
    metadata = {
        "query_mode": "mix",
        "keywords": {"high_level": ["a"], "low_level": ["b"]},
        "processing_info": {"total_entities_found": 1},
    }
    t = _build_trace(data, metadata)
    assert t["query_mode"] == "mix"
    assert t["keywords"] == {"high_level": ["a"], "low_level": ["b"]}
    assert t["entities"] == [{"name": "张三", "type": "person", "description": "x"}]
    assert t["relationships"][0] == {
        "src": "张三",
        "tgt": "字节跳动",
        "description": "y",
        "keywords": "任职",
        "weight": 1.0,
    }
    assert t["chunks"] == [{"content": "z", "chunk_id": "c1"}]
    # 检索原记录：不受后续高亮分层影响
    assert t["retrieved"] == {
        "entity_count": 1,
        "relation_count": 1,
        "entities": ["张三"],
        "relationships": ["张三->字节跳动"],
    }
    assert t["processing_info"]["total_entities_found"] == 1


# ---- M1：query() 的 anchor_text / evidence_text 透传 ----


class _FakeGraph:
    async def get_all_edges(self):
        return [
            {"source": "张三", "target": "字节跳动"},
            {"source": "北京", "target": "字节跳动"},
        ]


class _FakeVdb:
    async def query(self, text, top_k):
        return []


class _FakeRag:
    """最小 aquery 双件套：aquery_data 给上下文，aquery 给答案文本。"""

    def __init__(self, answer: str):
        self._answer = answer
        self.entities_vdb = _FakeVdb()
        self.chunk_entity_relation_graph = _FakeGraph()

    async def aquery_data(self, question, param):
        return {
            "status": "success",
            "data": {
                "entities": [
                    {"entity_name": "张三", "entity_type": "person", "description": ""},
                    {"entity_name": "字节跳动", "entity_type": "organization", "description": ""},
                    {"entity_name": "北京", "entity_type": "location", "description": ""},
                ],
                "relationships": [
                    {
                        "src_id": "张三",
                        "tgt_id": "字节跳动",
                        "description": "",
                        "keywords": "",
                        "weight": 1.0,
                    }
                ],
                "chunks": [],
            },
            "metadata": {"query_mode": "mix", "keywords": {"high_level": [], "low_level": []}},
        }

    async def aquery(self, question, param):
        return self._answer


def test_query_defaults_to_question_and_answer():
    """人类面：不传双文本时回落 anchor=问题、evidence=答案——与改造前行为一致。"""
    r = asyncio.run(query(_FakeRag("张三在字节跳动工作。"), "张三在哪工作"))
    assert r.trace["hit_layers"]["anchors"] == ["张三"]
    assert r.trace["hit_layers"]["cited"] == ["字节跳动"]


def test_query_dual_text_takes_evidence_from_task():
    """Agent 面：锚点取自 anchor_text(query)，证据取自 evidence_text(task)，答案文本不参与。"""
    r = asyncio.run(
        query(
            _FakeRag("（这句答案不含任何实体名）"),
            "他最近在忙什么",
            anchor_text="张三",
            evidence_text="张三在北京的字节跳动上班",
        )
    )
    assert r.trace["hit_layers"]["anchors"] == ["张三"]
    assert set(r.trace["hit_layers"]["cited"]) == {"北京", "字节跳动"}


# ---- M2：Agent 面不生成答案，但不许空着证据位 ----


class _NoAnswerRag(_FakeRag):
    """aquery 被调用即失败：用来证明 generate_answer=False 真的省掉了那次 LLM。"""

    async def aquery(self, question, param):
        raise AssertionError("generate_answer=False 时不该调 aquery")


def test_query_skip_answer_generation_uses_given_evidence():
    r = asyncio.run(
        query(
            _NoAnswerRag("（不会用到）"),
            "张三在哪工作",
            anchor_text="张三",
            evidence_text="张三在北京的字节跳动上班",
            generate_answer=False,
        )
    )
    assert r.answer == ""
    assert r.trace["hit_layers"]["anchors"] == ["张三"]
    assert set(r.trace["hit_layers"]["cited"]) == {"北京", "字节跳动"}


def test_query_skip_answer_generation_requires_evidence():
    with pytest.raises(ValueError, match="evidence_text"):
        asyncio.run(query(_NoAnswerRag("x"), "张三在哪工作", generate_answer=False))
