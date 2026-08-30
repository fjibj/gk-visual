"""S3/S7 测试：_hit_trace 三态分层（锚点/答案引用/路径）+ 分数只作旁证 + render 渲染。

纯函数测试：喂假 rag（假向量库 + 假图边表），确定性、不联网、不调 LLM。
"""

from __future__ import annotations

import asyncio

from graphkb.query import (
    QueryResult,
    _literal_names,
    _safe_score,
    _shortest_paths,
    _undirected_adjacency,
    _hit_trace,
)
from graphkb.render import render


def test_safe_score():
    assert _safe_score(0.5) == 0.5
    assert _safe_score("0.8") == 0.8
    assert _safe_score(None) is None
    assert _safe_score("bad") is None


def test_literal_names_long_name_first():
    names = ["周杰伦", "杰伦", "台北"]
    assert _literal_names("周杰伦在台北", names) == ["周杰伦", "台北"]
    assert _literal_names("", names) == []


def test_shortest_paths_keeps_all_equal_length_paths():
    """图上真有两条等长路时全显示——歧义是图的事实，不该由我们静默挑一条。"""
    adj = _undirected_adjacency([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"), ("A", "D")])
    assert _shortest_paths(adj, "A", "D") == [["A", "D"]]  # 1 跳最短，2 跳的两条被舍
    adj2 = _undirected_adjacency([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    assert _shortest_paths(adj2, "A", "D") == [["A", "B", "D"], ["A", "C", "D"]]
    assert _shortest_paths(adj2, "A", "孤岛") == []


class _FakeVdb:
    def __init__(self, results):
        self._results = results

    async def query(self, question, top_k):
        return self._results


class _BoomVdb:
    async def query(self, question, top_k):
        raise RuntimeError("vdb down")


class _FakeGraph:
    def __init__(self, edges=None):
        self._edges = edges or []

    async def get_all_edges(self):
        return self._edges


class _FakeRag:
    def __init__(self, entities_vdb=None, graph=None):
        self.entities_vdb = entities_vdb or _FakeVdb([])
        self.relationships_vdb = entities_vdb or _FakeVdb([])
        self.chunk_entity_relation_graph = graph or _FakeGraph()


def _trace(entities, rels, ll_kw=None, hl_kw=None):
    return {
        "keywords": {"high_level": hl_kw or [], "low_level": ll_kw or []},
        "entities": [{"name": n, "type": "person", "description": ""} for n in entities],
        "relationships": [
            {"src": s, "tgt": t, "description": "", "keywords": "", "weight": 1.0} for s, t in rels
        ],
    }


def _names(out):
    return {e["name"] for e in out["entities"]}


def _layers(out):
    return {e["name"]: e["layer"] for e in out["entities"]}


def _rel_keys(out):
    return {f"{r['src']}->{r['tgt']}" for r in out["relationships"]}


def test_hit_trace_anchor_and_cited_only():
    """命中 = 问题锚点 + 答案引用到的点 + 二者之间的路径；捞到但没用的邻居不着色。"""
    rag = _FakeRag(
        entities_vdb=_FakeVdb(
            [
                {"entity_name": "张三", "distance": 0.539},
                {"entity_name": "软件工程师", "distance": 0.459},
            ]
        )
    )
    trace = _trace(
        ["张三", "字节跳动", "北京", "李雷"],
        [("字节跳动", "张三"), ("北京", "张三"), ("李雷", "腾讯")],
        ll_kw=["张三"],
    )
    out = asyncio.run(_hit_trace(rag, "张三在哪工作", "张三在字节跳动工作，担任后端工程师。", trace))

    assert _names(out) == {"张三", "字节跳动"}
    assert _layers(out) == {"张三": "anchor", "字节跳动": "cited"}
    assert _rel_keys(out) == {"字节跳动->张三"}
    # 捞到未用的仍然可见（在候选列表里），只是不上色
    assert {r["name"] for r in out["hit_layers"]["recall_only"]} == {"北京", "李雷", "腾讯"}
    assert out["hit_layers"]["anchor_mode"] == "literal"


def test_hit_trace_cross_component_keeps_both_clusters():
    """对比题天然跨分量：两个簇都要留着，「无路径」记成信息而不是被阈值抹掉。"""
    rag = _FakeRag()
    trace = _trace(
        ["腾讯", "深圳", "字节跳动", "北京"],
        [("深圳", "腾讯"), ("北京", "字节跳动")],
        ll_kw=["腾讯", "字节跳动"],
    )
    q = "腾讯和字节跳动的总部在哪个城市"
    a = "腾讯总部位于深圳，字节跳动总部位于北京。"
    out = asyncio.run(_hit_trace(rag, q, a, trace))

    assert _names(out) == {"腾讯", "深圳", "字节跳动", "北京"}
    assert _rel_keys(out) == {"深圳->腾讯", "北京->字节跳动"}
    disc = out["hit_layers"]["disconnected"]
    assert len(disc) == 1 and {disc[0]["a"], disc[0]["b"]} == {"腾讯", "字节跳动"}
    assert len(out["hit_layers"]["paths"]) == 2  # 深圳↔腾讯、北京↔字节跳动


def test_hit_trace_no_score_gate_anymore():
    """低分候选不再被阈值剔除出「可见」范围：它进候选列表，但因非锚点/非路径而不上色。"""
    rag = _FakeRag(
        entities_vdb=_FakeVdb(
            [
                {"entity_name": "腾讯", "distance": 0.759},
                {"entity_name": "深圳", "distance": 0.678},
                {"entity_name": "李雷", "distance": 0.626},
                {"entity_name": "字节跳动", "distance": 0.487},
            ]
        )
    )
    trace = _trace(
        ["腾讯", "深圳", "李雷", "字节跳动"],
        [("深圳", "腾讯"), ("李雷", "腾讯"), ("北京", "字节跳动")],
        ll_kw=["腾讯"],
    )
    out = asyncio.run(_hit_trace(rag, "腾讯总部在哪", "腾讯总部位于深圳。", trace))

    assert _names(out) == {"腾讯", "深圳"}
    assert _layers(out) == {"腾讯": "anchor", "深圳": "cited"}
    recall = {r["name"]: r["score"] for r in out["hit_layers"]["recall_only"]}
    assert recall["字节跳动"] == 0.487 and recall["李雷"] == 0.626
    assert "hit_filter" not in out  # 旧的分数闸门字段已删除


def test_hit_trace_path_node_layer():
    """答案引用的点要靠中间节点连上锚点时，中间节点标为 path 层。"""
    rag = _FakeRag()
    trace = _trace(
        ["蔡依林", "周杰伦", "演唱会", "台北"],
        [("周杰伦", "演唱会"), ("演唱会", "蔡依林"), ("台北", "演唱会")],
        ll_kw=["蔡依林", "周杰伦"],
    )
    q = "蔡依林和周杰伦是什么关系"
    a = "蔡依林参加了周杰伦在台北举办的演唱会。"
    out = asyncio.run(_hit_trace(rag, q, a, trace))

    assert _names(out) == {"蔡依林", "周杰伦", "演唱会", "台北"}
    assert _layers(out)["台北"] == "cited"
    assert _layers(out)["演唱会"] in ("cited", "path")
    hops = {p["hops"] for p in out["hit_layers"]["paths"]}
    assert hops == {1, 2}  # 台北↔蔡依林 走 2 跳；直接相邻的 1 跳


def test_hit_trace_uses_full_graph_for_paths():
    """上下文子图缺中间边时，用全图补出路径（否则 2 跳证据会被误判为「连不上」）。"""
    rag = _FakeRag(
        graph=_FakeGraph(
            [
                {"source": "周杰伦", "target": "演唱会", "description": "办", "keywords": "", "weight": 1},
                {"source": "演唱会", "target": "台北", "description": "地点", "keywords": "", "weight": 1},
            ]
        )
    )
    trace = _trace(["周杰伦", "台北"], [], ll_kw=["周杰伦"])
    out = asyncio.run(_hit_trace(rag, "周杰伦在哪里开演唱会", "演唱会在台北举办。", trace))

    assert _names(out) == {"周杰伦", "台北", "演唱会"}
    assert _layers(out)["演唱会"] == "path"
    assert _rel_keys(out) == {"周杰伦->演唱会", "演唱会->台北"}


def test_hit_trace_vector_fallback_is_flagged():
    """问题里没有字面实体名（代词/省略）→ 退到向量 top1 当锚点，并显式标注不可靠。"""
    rag = _FakeRag(
        entities_vdb=_FakeVdb([{"entity_name": "张三", "distance": 0.4}, {"entity_name": "字节跳动", "distance": 0.3}])
    )
    trace = _trace(["张三", "字节跳动"], [("字节跳动", "张三")], ll_kw=["他"])
    out = asyncio.run(_hit_trace(rag, "他最近怎么样", "没有更多记录。", trace))

    assert out["hit_layers"]["anchor_mode"] == "vector_fallback"
    assert out["hit_layers"]["anchors"] == ["张三"]
    assert _names(out) == {"张三"}
    assert out["relationships"] == []  # 答案没引用任何关系 → 不硬凑邻居充数


def test_hit_trace_flags_entities_missing_from_graph():
    """问「张三认识姚明吗」而姚明从未入库：图上没这个点要显式说出来，不能拿邻居充数。"""
    rag = _FakeRag(entities_vdb=_FakeVdb([{"entity_name": "张三", "distance": 0.6}]))
    trace = _trace(["张三", "北京"], [("北京", "张三")], ll_kw=["张三", "姚明", "张三的公司"])
    out = asyncio.run(_hit_trace(rag, "张三认识姚明吗", "无法确认。", trace))

    # 「张三的公司」是 LLM 拆出的短语，能包回已命中的「张三」，不当作缺实体
    assert out["hit_layers"]["unmatched_keywords"] == ["姚明"]
    assert _names(out) == {"张三"}


def test_hit_trace_degraded_on_error():
    rag = _FakeRag(entities_vdb=_BoomVdb())
    trace = _trace(["字节跳动"], [("字节跳动", "张一鸣")])
    out = asyncio.run(_hit_trace(rag, "q", "a", trace))
    # 降级：保留全上下文实体、不假装分层、score 为 None
    assert _names(out) == {"字节跳动"}
    assert all(e["layer"] is None for e in out["entities"])
    assert out["hit_layers"]["anchor_mode"] == "vdb_error"


def test_hit_trace_no_anchor_no_citation_keeps_context():
    """既没锚点也没答案引用 → 不编造分层，上下文原样交出（score 无）。"""
    rag = _FakeRag(entities_vdb=_FakeVdb([{"entity_name": "张三"}]))
    trace = _trace(["张三", "北京"], [("北京", "张三")])
    out = asyncio.run(_hit_trace(rag, "随便说说", "无可奉告。", trace))
    assert out["hit_layers"]["anchor_mode"] == "no_anchor"
    assert _names(out) == {"张三", "北京"}


def test_render_hit():
    result = QueryResult(
        question="谁创立了字节跳动？",
        answer="张一鸣",
        trace={
            "keywords": {"high_level": ["创始人"], "low_level": ["字节跳动"]},
            "entities": [
                {"name": "字节跳动", "type": "organization", "score": 0.8, "layer": "anchor"},
                {"name": "张一鸣", "type": "person", "score": 0.67, "layer": "cited"},
            ],
            "relationships": [{"src": "字节跳动", "tgt": "张一鸣", "score": 0.67, "layer": "path"}],
            "chunks": [{"content": "字节跳动由张一鸣创立。"}],
            "hit_layers": {
                "anchor_mode": "literal",
                "anchors": ["字节跳动"],
                "cited": ["张一鸣"],
                "paths": [{"from": "字节跳动", "to": "张一鸣", "hops": 1, "paths": [["字节跳动", "张一鸣"]]}],
                "disconnected": [],
                "recall_only": [{"name": "北京", "score": 0.31}],
            },
        },
        trace_hit=True,
    )
    text = render(result)
    assert "[锚点] 字节跳动" in text
    assert "[答案引用] 张一鸣" in text
    assert "↳ 路径(1跳): 字节跳动 → 张一鸣" in text
    assert "捞到未用 (1)" in text
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
