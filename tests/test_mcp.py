"""Agent 记忆面（M2）单元测试：全离线，LLM/embedding 走假对象。

分两层：
  · `MemoryTools`——纯逻辑，不依赖 MCP SDK（SDK 没装也能跑）
  · `mcp_server`——适配器接线，需要 mcp（CI 装 `.[dev,mcp]`），用 importorskip 兜底
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from graphkb.config import Config
from graphkb.memory_api import MemoryTools, build_answer_context, estimate_tokens, resolve_budget

# ---------------------------------------------------------------- 假对象


class _FakeGraph:
    def __init__(self, nodes=None, edges=None):
        self.nodes = [
            {"entity_id": "张三", "entity_type": "person", "description": "张三是一名工程师", "source_id": "chunk-1"},
            {"entity_id": "字节跳动", "entity_type": "organization", "description": "一家公司", "source_id": "chunk-1"},
            {"entity_id": "北京", "entity_type": "location", "description": "城市", "source_id": "chunk-1"},
        ] if nodes is None else nodes
        self.edges = [
            {"source": "张三", "target": "字节跳动", "description": "任职", "keywords": "任职", "source_id": "chunk-1"},
            {"source": "北京", "target": "字节跳动", "description": "总部位于", "keywords": "总部", "source_id": "chunk-1"},
        ] if edges is None else edges

    async def get_all_nodes(self):
        return self.nodes

    async def get_all_edges(self):
        return self.edges

    # --- memory.expand 用：按名字取单点/单边 ---
    def _node_map(self):
        out = {}
        for n in self.nodes:
            name = str(n.get("entity_id") or n.get("id") or "")
            out[name] = n
        return out

    async def get_node(self, node_id):
        return self._node_map().get(str(node_id))

    async def get_edge(self, src, tgt):
        for e in self.edges:
            if str(e.get("source")) == str(src) and str(e.get("target")) == str(tgt):
                return e
            if str(e.get("source")) == str(tgt) and str(e.get("target")) == str(src):
                return e
        return None


def _with_doc_fields(row):
    """假块存储：缺字段时补上文档身份（真 LightRAG 每条 chunk 都有 full_doc_id/file_path）。"""
    if not row:
        return row
    return {**row, "full_doc_id": row.get("full_doc_id", "doc-1"), "file_path": row.get("file_path", "张三简历")}


class _FakeTextChunks:
    def __init__(self, rows=None):
        self.rows = rows or {
            "c1": {"content": "张三在字节跳动工作，常驻北京。"},
            "chunk-1": {"content": "张三在北京的字节跳动上班。"},
        }

    async def get_by_id(self, chunk_id):
        return _with_doc_fields(self.rows.get(str(chunk_id)))

    async def get_by_ids(self, ids):
        # 与 LightRAG 一致：顺序对齐，取不到的位置给 None
        return [_with_doc_fields(self.rows.get(str(i))) for i in ids]


class _FakeVdb:
    def __init__(self, scores=None, boom=False):
        self.scores = scores or {}
        self.boom = boom

    async def query(self, text, top_k):
        if self.boom:
            raise RuntimeError("向量库炸了")
        return [{"entity_name": n, "distance": s} for n, s in self.scores.items()][:top_k]


class _FakeDocStatus:
    def __init__(self, docs: dict):
        self._docs = docs

    async def get_docs_by_statuses(self, statuses, strict=False):
        return self._docs


class _FakeRag:
    """检索 + 写入两用假图。`aquery` 默认直接失败——Agent 模式本就不该生成答案。"""

    def __init__(self, answer: str = "张三在字节跳动工作。", scores=None, vdb_boom=False):
        self._answer = answer
        self.docs: dict = {}
        self.calls: list = []
        self.chunk_entity_relation_graph = _FakeGraph()
        self.entities_vdb = _FakeVdb(scores=scores, boom=vdb_boom)
        self.doc_status = _FakeDocStatus(self.docs)
        self.text_chunks = _FakeTextChunks()

    async def aquery_data(self, question, param):
        return {
            "status": "success",
            "data": {
                "entities": [
                    {"entity_name": "张三", "entity_type": "person", "description": "工程师"},
                    {"entity_name": "字节跳动", "entity_type": "organization", "description": "公司"},
                    {"entity_name": "北京", "entity_type": "location", "description": "城市"},
                ],
                "relationships": [
                    {"src_id": "张三", "tgt_id": "字节跳动", "description": "任职", "keywords": "任职", "weight": 1.0}
                ],
                "chunks": [{"content": "张三在字节跳动工作，常驻北京。", "chunk_id": "c1"}],
            },
            "metadata": {"query_mode": "mix", "keywords": {"high_level": [], "low_level": []}},
        }

    async def aquery(self, question, param):
        if self._answer is None:
            raise AssertionError("agent 模式不该调 aquery（那是答案生成，白花一次 LLM）")
        return self._answer

    async def ainsert(self, text, ids=None, file_paths=None):
        self.calls.append(("insert", ids))
        self.docs[ids[0]] = SimpleNamespace(
            file_path=file_paths[0], content_length=len(text), chunks_list=["chunk-1"]
        )

    async def adelete_by_doc_id(self, doc_id):
        self.calls.append(("delete", doc_id))
        self.docs.pop(doc_id, None)
        return SimpleNamespace(status="success", message="ok")


def _tools(**kwargs) -> tuple[MemoryTools, _FakeRag]:
    rag = _FakeRag(**kwargs)
    return MemoryTools(Config(), rag), rag


# ---------------------------------------------------------------- memory.search


def test_search_requires_task():
    tools, _ = _tools()
    with pytest.raises(ValueError, match="context.task"):
        asyncio.run(tools.search({"query": "张三在哪工作"}))


def test_search_rejects_non_object_context():
    tools, _ = _tools()
    with pytest.raises(ValueError, match="context 必须是对象"):
        asyncio.run(tools.search("张三在哪工作"))


def test_search_agent_mode_splits_roles_and_skips_answer_llm():
    """Agent 主路：锚点来自 query、证据来自 task，且不生成答案（aquery 若被调会 AssertionError）。"""
    tools, rag = _tools(answer=None)
    out = asyncio.run(
        tools.search(
            {"query": "张三在哪工作", "task": "整理张三的交货地点：他常驻北京，单位是字节跳动"},
            caller="harness@test",
        )
    )
    assert out["mode"] == "agent"
    assert out["degraded"] is False, out["warnings"]
    assert out["reason"] is None
    assert out["trace"]["anchors"] == ["张三"]
    assert set(out["trace"]["cited"]) == {"字节跳动", "北京"}
    assert out["trace"]["paths"], "锚点与证据之间应给出最短路"
    assert out["version"] == "1"
    assert out["answer_context"], "命中时应给出可注入上下文"
    assert "[anchor] 张三" in out["answer_context"]
    # 溯源（M4）：命中项必须带「从文档抽的 / 人手工加的」与来源文档
    assert all(e["origin"] == "extracted" for e in out["hits"]["entities"])
    assert all(e["provenance"]["docs"] == ["张三简历"] for e in out["hits"]["entities"])
    assert all(r["origin"] == "extracted" for r in out["hits"]["relationships"])
    assert rag.calls == []


def test_search_texts_equal_degrades_and_falls_back_to_human_semantics():
    """query 缺省 = task：证据层无法分离，必须显式降级，而不是装作分层成功。

    这里能直接看到退化本身：task 里的实体全被当成锚点，cited 塜成空——
    就是探针 B §4 那个「看着正常、实则证据位已死」的形状。
    """
    tools, _ = _tools()
    out = asyncio.run(tools.search({"task": "张三在字节跳动工作"}))
    assert out["degraded"] is True
    assert out["reason"] == "texts_equal"
    assert out["mode"] == "human"
    assert set(out["trace"]["anchors"]) == {"张三", "字节跳动"}
    assert out["trace"]["cited"] == [], "证据层塔成空——所以才要降级告知"
    assert any("context.query" in w for w in out["warnings"])


def test_search_vdb_error_degrades():
    tools, _ = _tools(vdb_boom=True)
    out = asyncio.run(tools.search({"query": "张三在哪工作", "task": "他常驻北京"}))
    assert out["degraded"] is True
    assert out["reason"] == "vdb_error"
    assert out["trace"]["anchor_mode"] == "vdb_error"
    assert all(e["layer"] is None for e in out["hits"]["entities"]), "不猜锚点、不分层"


def test_search_no_anchor_degrades():
    tools, _ = _tools()
    out = asyncio.run(tools.search({"query": "他最近在忙什么", "task": "他也不太清楚"}))
    assert out["degraded"] is True
    assert out["reason"] == "no_anchor"


def test_search_budget_passthrough():
    tools, _ = _tools()
    out = asyncio.run(
        tools.search(
            {"query": "张三在哪工作", "task": "张三在字节跳动上班"},
            budget={"top_k": 2, "max_hops": 2, "max_paths": 3, "max_context_tokens": 500},
        )
    )
    used = out["trace"]["budget_used"]
    assert used["top_k"] == 2
    assert used["max_hops"] == 2
    assert used["max_paths"] == 3
    assert used["context_tokens"] == 500
    assert used["context_used"] > 0
    assert used["context_inline"] > 0
    assert used["context_spilled"] == 0
    assert out["spill_refs"] == []


def test_search_budget_truncation_is_reported_not_silent():
    """预算装不下：不静默丢，全部进 spill_refs，并回 reason=budget_truncated。"""
    tools, _ = _tools()
    out = asyncio.run(
        tools.search(
            {"query": "张三在哪工作", "task": "张三在字节跳动上班"},
            budget={"max_context_tokens": 1},
        )
    )
    assert out["degraded"] is True
    assert out["reason"] == "budget_truncated"
    assert out["trace"]["budget_used"]["context_spilled"] > 0
    assert out["answer_context"] == ""
    assert out["spill_refs"], "溢出必须变成可取回的引用，而不是丢掉"
    assert any("memory.expand" in w for w in out["warnings"])


def test_search_bad_budget_rejected():
    tools, _ = _tools()
    for bad in ({"top_k": 0}, {"max_hops": -1}, {"max_context_tokens": 0}):
        with pytest.raises(ValueError, match="≥1"):
            asyncio.run(tools.search({"query": "张三在哪", "task": "张三在北京"}, budget=bad))


def test_search_bad_mode_rejected():
    tools, _ = _tools()
    with pytest.raises(ValueError, match="mode 只能是"):
        asyncio.run(tools.search({"query": "张三在哪", "task": "张三在北京"}, mode="robot"))


def test_search_flags_empty_evidence_layer():
    """锚点有、证据没有：不装 degraded，但用结构化字段 + 警告把“分层只停半路”暴露出来。

    真实场景就在眼前：agent 常写“帮我整理周报”这种任务文本，里面没有实体名，
    证据层于是静默不亮。只靠 warnings 容易被跳过，所以 trace 里也要有个布尔。
    """
    tools, _ = _tools()
    out = asyncio.run(
        tools.search({"query": "张三在哪工作", "task": "帮他整理一份周报，周五交"})
    )
    assert out["degraded"] is False
    assert out["trace"]["anchors"] == ["张三"]
    assert out["trace"]["cited"] == []
    assert out["trace"]["evidence_empty"] is True
    assert any("证据层未触发" in w for w in out["warnings"])


def test_search_full_layers_do_not_flag_evidence_empty():
    tools, _ = _tools()
    out = asyncio.run(
        tools.search({"query": "张三在哪工作", "task": "张三常驻北京，单位是字节跳动"})
    )
    assert out["trace"]["evidence_empty"] is False
    assert not any("证据层未触发" in w for w in out["warnings"])


def test_search_no_hit_returns_empty_context_not_fabrication():
    """检索全空：answer_context 必须是空串，并如实告知，不许编内容。"""

    class _EmptyRag(_FakeRag):
        async def aquery_data(self, question, param):
            return {
                "status": "failure",
                "data": {},
                "metadata": {"failure_reason": "no_results"},
            }

    tools = MemoryTools(Config(), _EmptyRag())
    out = asyncio.run(tools.search({"query": "张三在哪工作", "task": "张三在字节跳动"}))
    assert out["answer_context"] == ""
    assert out["hits"]["entities"] == []
    assert any("不会编造" in w for w in out["warnings"])


# ---------------------------------------------------------------- memory.ingest


def test_ingest_wait_returns_done_and_status_is_queryable():
    tools, rag = _tools()

    async def scenario():
        out = await tools.ingest(source="session", content="张三在字节跳动工作", title="会话A", wait=True)
        assert out["status"] == "done", out["error"]
        return tools.ingest_status(out["job_id"])

    status = asyncio.run(scenario())
    assert status["status"] == "done"
    assert status["doc_id"] == "会话A"
    assert status["result"]["doc_id"] == "会话A"
    assert status["result"]["created"] is True
    assert rag.calls == [("insert", ["会话A"])]


def test_ingest_default_is_async_and_finishes_in_background():
    tools, _ = _tools()

    async def scenario():
        out = await tools.ingest(source="note", content="随手记：明天去北京", title="随手记")
        assert out["job_id"].startswith("job-")
        await asyncio.sleep(0.05)  # 让后台任务跑完
        return tools.ingest_status(out["job_id"])

    status = asyncio.run(scenario())
    assert status["status"] == "done"
    assert status["progress"] == "完成"


def test_ingest_rejects_empty_content_and_bad_source():
    tools, _ = _tools()
    with pytest.raises(ValueError, match="content 不能为空"):
        asyncio.run(tools.ingest(source="doc", content="   "))
    with pytest.raises(ValueError, match="source 只能是"):
        asyncio.run(tools.ingest(source="docc", content="正文"))


def test_ingest_failure_is_reported_not_swallowed():
    class _BrokenRag(_FakeRag):
        async def ainsert(self, text, ids=None, file_paths=None):
            raise RuntimeError("LLM 超时")

    tools = MemoryTools(Config(), _BrokenRag())
    out = asyncio.run(tools.ingest(source="doc", content="正文", title="坏文档", wait=True))
    assert out["status"] == "error"
    assert "LLM 超时" in (out["error"] or "")


def test_ingest_status_unknown_job_is_structured():
    tools, _ = _tools()
    out = tools.ingest_status("job-nope")
    assert out["status"] == "unknown"
    assert "重启即清空" in out["error"]


def test_ingest_manual_origin_warns_it_is_not_persisted():
    tools, _ = _tools()
    out = asyncio.run(tools.ingest(source="note", content="手写内容", origin="manual", wait=True))
    assert out["origin"] == "manual"
    assert any("文档级" in w for w in out["warnings"]), out["warnings"]


# ---------------------------------------------------------------- 预算与上下文构建


def test_estimate_tokens_is_conservative():
    assert estimate_tokens("张三") == 2
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0


def test_resolve_budget_defaults_come_from_config():
    b = resolve_budget(None, Config().retrieval)
    assert b.retrieval.hit_top_k == 5
    assert b.max_context_tokens == 800
    assert b.as_dict()["context_tokens"] == 800


# ---------------------------------------------------------------- M3：Inline & Spill


def test_layer_budget_path_layer_is_compact():
    """path 层只带名字 + 类型：额度小、不带描述（描述可在 spill 摘要里，也能用 entity: 取）。"""
    entities = [
        {"name": "锚点", "type": "concept", "layer": "anchor", "description": "锚点的完整描述" * 8},
        {"name": "中间", "type": "concept", "layer": "path", "description": "路径节点的完整描述" * 8},
    ]
    bundle = build_answer_context(entities, [], [], 800)
    lines = bundle.text.splitlines()
    assert any(ln.startswith("[anchor] 锚点") and "：" in ln for ln in lines)
    path_line = next(ln for ln in lines if ln.startswith("[path] 中间"))
    assert "（concept）" in path_line
    assert "：" not in path_line, path_line
    assert bundle.layer_used["path"]["tokens"] < bundle.layer_used["anchor"]["tokens"]


def test_layer_budget_unused_share_flows_forward():
    """锚点没花完的额度要传给后面的层，不能因为分层而白白扔掉。"""
    entities = [{"name": "锚点", "type": "t", "layer": "anchor", "description": "短"}]
    relationships = [
        {"src": "锚点", "tgt": f"证据{i}", "layer": "direct", "description": "关系描述" * 6}
        for i in range(3)
    ]
    bundle = build_answer_context(entities, relationships, [], 300)
    assert bundle.layer_used["direct"]["inline"] == 3, bundle.layer_used


def test_layer_budget_soft_cap_when_nothing_else_competes():
    """后面没人抢时，本层可以吃满（份额是软上限）——否则“预算恰好够用”会被错杀。"""
    entities = [{"name": "唯一一个", "type": "t", "layer": "anchor", "description": "描述" * 20}]
    roomy = build_answer_context(entities, [], [], 2000)
    need = roomy.used_tokens
    exact = build_answer_context(entities, [], [], need)
    assert exact.spill_refs == []
    assert exact.used_tokens == need


def test_budget_boundary_exact_fit_vs_one_under():
    """刚好装下 vs 少 1 个 token：边界两侧行为必须可区分且可预测。"""
    tools, _ = _tools()
    args = {"query": "张三在哪工作", "task": "张三在字节跳动上班，常驻北京"}

    roomy = asyncio.run(tools.search(args, budget={"max_context_tokens": 10_000}))
    need = roomy["trace"]["budget_used"]["context_used"]
    assert need > 1 and roomy["spill_refs"] == []

    exact = asyncio.run(tools.search(args, budget={"max_context_tokens": need}))
    assert exact["spill_refs"] == [], "预算恰好等于需求时不该溢出"
    assert exact["trace"]["budget_used"]["context_used"] == need

    tight = asyncio.run(tools.search(args, budget={"max_context_tokens": need - 1}))
    assert tight["spill_refs"], "少 1 个 token 就该有内容被 spill 出去"
    assert tight["reason"] == "budget_truncated"
    assert tight["trace"]["budget_used"]["context_spilled"] == len(tight["spill_refs"])


def test_spill_refs_are_addressable_and_carry_cost():
    tools, _ = _tools()
    out = asyncio.run(
        tools.search(
            {"query": "张三在哪工作", "task": "张三在字节跳动上班，常驻北京"},
            budget={"max_context_tokens": 12},
        )
    )
    assert out["spill_refs"]
    for ref in out["spill_refs"]:
        assert set(ref) == {"ref", "kind", "summary", "tokens"}
        assert ref["kind"] in {"entity", "relation", "chunk"}
        assert ref["ref"].startswith(("entity:", "relation:", "chunk:"))
        assert ref["summary"] and ref["tokens"] > 0
    # 溢出内容不应“同时”留在 answer_context 里
    for ref in out["spill_refs"]:
        if ref["kind"] == "entity":
            assert f"[anchor] {ref['ref'].split(':', 1)[1]}" not in out["answer_context"]


def test_search_then_expand_roundtrip():
    """冒烟场景：预算卡死后取回一条 spill_ref，内容真的还在（引用无状态，可解析）。"""
    tools, _ = _tools()
    out = asyncio.run(
        tools.search(
            {"query": "张三在哪工作", "task": "张三在字节跳动上班"},
            budget={"max_context_tokens": 1},
        )
    )
    refs = [r["ref"] for r in out["spill_refs"]]
    assert refs
    got = asyncio.run(tools.expand(refs))
    assert not got["missing"]
    assert len(got["items"]) == len(refs)
    for item in got["items"]:
        assert item["text"].strip()
        assert item["truncated"] is False


def test_expand_entity_relation_chunk():
    tools, _ = _tools()
    got = asyncio.run(
        tools.expand(["entity:张三", "relation:张三->字节跳动", "chunk:c1"])
    )
    assert got["missing"] == []
    by_kind = {i["kind"]: i["text"] for i in got["items"]}
    assert "张三" in by_kind["entity"] and "工程师" in by_kind["entity"]
    assert "->" in by_kind["relation"]
    assert "字节跳动" in by_kind["chunk"]


def test_expand_reports_missing_instead_of_fabricating():
    tools, _ = _tools()
    got = asyncio.run(
        tools.expand(["entity:不存在的人", "chunk:nope", "planet:Mars", "relation:无箭头"])
    )
    assert got["items"] == []
    reasons = {m["ref"]: m["reason"] for m in got["missing"]}
    assert "没有这个实体" in reasons["entity:不存在的人"]
    assert "chunk" in reasons["chunk:nope"]
    assert "未知引用类型" in reasons["planet:Mars"]
    assert "relation:A->B" in reasons["relation:无箭头"]


def test_expand_validates_inputs():
    tools, _ = _tools()
    with pytest.raises(ValueError, match="不能为空"):
        asyncio.run(tools.expand([]))
    with pytest.raises(ValueError, match="最多取"):
        asyncio.run(tools.expand([f"entity:e{i}" for i in range(21)]))
    with pytest.raises(ValueError, match="max_tokens"):
        asyncio.run(tools.expand(["entity:张三"], max_tokens=0))


def test_expand_truncates_but_says_so():
    tools, _ = _tools()
    got = asyncio.run(tools.expand(["entity:张三"], max_tokens=1))
    item = got["items"][0]
    assert item["truncated"] is True
    assert item["tokens"] > 1
    assert item["text"].endswith("…")


def test_descriptions_are_flattened_for_reading():
    """LightRAG 用 <SEP> 拼多段描述，直出就是天书，取回时要抖平。"""
    tools, rag = _tools()
    rag.chunk_entity_relation_graph.nodes[0]["description"] = "一个人<SEP>张三是一名工程师"
    got = asyncio.run(tools.expand(["entity:张三"]))
    text = got["items"][0]["text"]
    assert "<SEP>" not in text
    assert "一个人" in text and "工程师" in text


# ---------------------------------------------------------------- M4：溯源标签


def test_search_marks_manual_entity_and_relation():
    """人工加的东西在 agent 面也得一眼可辨：origin=mixed/manual + provenance.manual。"""
    tools, rag = _tools(answer=None)
    g = rag.chunk_entity_relation_graph
    # 同一实体被人工改过 -> source_id 里两样都有（LightRAG 编辑后就是这个形状）
    g.nodes.append(
        {
            "entity_id": "张三",
            "entity_type": "person",
            "description": "张三是一名工程师",
            "source_id": "chunk-1<SEP>manual_creation",
        }
    )
    g.edges.insert(
        0,
        {
            "source": "张三",
            "target": "字节跳动",
            "description": "任职",
            "keywords": "任职",
            "source_id": "manual_creation",
        },
    )
    out = asyncio.run(
        tools.search({"query": "张三在哪工作", "task": "张三在字节跳动上班，常驻北京"})
    )
    ents = {e["name"]: e for e in out["hits"]["entities"]}
    assert ents["张三"]["origin"] == "mixed"
    assert ents["张三"]["provenance"]["manual"] is True
    assert ents["张三"]["provenance"]["docs"] == ["张三简历"]
    assert ents["北京"]["origin"] == "extracted"
    rels = {(r["src"], r["tgt"]): r for r in out["hits"]["relationships"]}
    assert rels[("张三", "字节跳动")]["origin"] == "manual"


def test_search_origin_is_unknown_not_none_when_unreadable():
    """溯源读不到时给 unknown，而不是 null：字段恒在，调用方不用写两种分支。"""
    tools, rag = _tools(answer=None)
    rag.chunk_entity_relation_graph.nodes = [
        {"entity_id": "张三", "entity_type": "person", "description": "工程师"}
    ]
    out = asyncio.run(tools.search({"query": "张三在哪工作", "task": "张三在北京上班"}))
    ent = next(e for e in out["hits"]["entities"] if e["name"] == "张三")
    assert ent["origin"] == "unknown"
    assert ent["provenance"]["chunks"] == 0


def test_expand_items_carry_provenance():
    """取回的内容同样带来源——同一份真相，不在两个地方各说一套。"""
    tools, _ = _tools()
    out = asyncio.run(tools.expand(["entity:张三", "relation:张三->字节跳动", "chunk:c1"]))
    by_ref = {i["ref"]: i for i in out["items"]}
    assert by_ref["entity:张三"]["origin"] == "extracted"
    assert by_ref["entity:张三"]["provenance"]["docs"] == ["张三简历"]
    assert by_ref["relation:张三->字节跳动"]["origin"] == "extracted"
    assert by_ref["chunk:c1"]["origin"] == "extracted"
    assert by_ref["chunk:c1"]["provenance"]["docs"] == ["张三简历"]


# ---------------------------------------------------------------- MCP 适配器接线


# ---------------------------------------------------------------- 注入里的无关块


class _MixedChunkRag(_FakeRag):
    """命中实体引自 chunk-1；另外再捞回一块与实体完全无关的块（李雷/腾讯）。"""

    async def aquery_data(self, question, param):
        data = await super().aquery_data(question, param)
        data["data"]["chunks"] = [
            {"content": "张三在北京的字节跳动上班。", "chunk_id": "chunk-1"},
            {"content": "李雷在腾讯工作，腾讯总部位于深圳。", "chunk_id": "c-unrelated"},
        ]
        return data


def test_unrelated_chunk_not_injected_but_kept_for_audit():
    """向量召回的块不等于命中：与命中实体没有来源交集的块不进注入，但审计面不删。

    这是 S7 那条不变量的反面案例——「话题相似但实体无关的不得算命中」。
    块里出现李雷/腾讯，与锚点张三没有来源交集，塞进 agent 上下文就是拿预算买噪声。
    """
    rag = _MixedChunkRag(answer=None)
    tools = MemoryTools(Config(), rag)
    out = asyncio.run(
        tools.search({"query": "张三在哪工作", "task": "张三在字节跳动上班，常驻北京"})
    )
    assert "[chunk] 张三在北京的字节跳动上班" in out["answer_context"]
    assert "李雷" not in out["answer_context"], out["answer_context"]
    marks = {c["chunk_id"]: c["linked"] for c in out["hits"]["chunks"]}
    assert marks == {"chunk-1": True, "c-unrelated": False}
    assert any("没有来源交集" in w for w in out["warnings"]), out["warnings"]
    assert out["degraded"] is False, "过滤无关块不是降级——命中判据没有变"


def test_chunks_kept_when_provenance_is_unavailable():
    """溯源拿不到时不能把注入饿死：退回全量块，并标 linked=None（不知道，而不是「无关」）。"""
    tools, rag = _tools(answer=None)
    rag.chunk_entity_relation_graph.nodes = [
        {"entity_id": "张三", "entity_type": "person", "description": "工程师"},
        {"entity_id": "北京", "entity_type": "location", "description": "城市"},
        {"entity_id": "字节跳动", "entity_type": "organization", "description": "公司"},
    ]
    rag.chunk_entity_relation_graph.edges = [
        {"source": "张三", "target": "字节跳动", "description": "任职", "keywords": "任职"}
    ]
    out = asyncio.run(
        tools.search({"query": "张三在哪工作", "task": "张三在字节跳动上班，常驻北京"})
    )
    assert "[chunk]" in out["answer_context"]
    assert all(c["linked"] is None for c in out["hits"]["chunks"])


def test_mcp_server_registers_four_tools():
    pytest.importorskip("mcp", reason="MCP extra 没装：pip install -e \".[dev,mcp]\"")
    from graphkb.mcp_server import build_server

    app = build_server()
    tools = {t.name: t for t in app._tool_manager.list_tools()}
    assert set(tools) == {"memory.search", "memory.expand", "memory.ingest", "memory.ingest_status"}
    # Context 是注入参数，不能出现在工具的入参 schema 里
    search_params = tools["memory.search"].parameters
    assert "context" in search_params["properties"]
    assert "ctx" not in search_params["properties"]
    assert "refs" in tools["memory.expand"].parameters["properties"]


def test_pinned_sdk_still_speaks_2025_11_25():
    """Cola 侧报的协议版本必须还在 SDK 的握手列表里——这是 M2 的地基。"""
    pytest.importorskip("mcp", reason="MCP extra 没装")
    from graphkb.mcp_server import EXPECTED_PROTOCOL_VERSION, check_protocol_support

    assert check_protocol_support() == [], (
        f"当前 mcp SDK 不再支持 {EXPECTED_PROTOCOL_VERSION}：升级适配器或回退 SDK 版本"
    )
