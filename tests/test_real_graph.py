"""真图回归：拿录下来的真实 workspace 复算整条链路（零网络、零 LLM、CI 可跑）。

这套用例回答的是「换成真图会不会坏」：小图（4~5 个节点）证明不了的东西——
路径中间节点、`<SEP>` 拼接的长描述、80 个实体名同时挂在探针上、预算被撑满——
都在这里压一遍。

夹具由 `scripts/capture_real_fixture.py` 录制：
· `graph_chunk_entity_relation.graphml`：从真实图 BFS 出来的一张子图（默认脱敏，结构不变）；
· `case_*.retrieval.json`：`aquery_data` 的原样返回；
· `case_*.vdb.json`：`entities_vdb.query` 的原样返回；
· `manifest.json`：图规模 + 每个 case 的锚/证据文本。

下面两组：
· **回放组**（默认跑）：夹具进内存，`query()` → `_hit_trace` → 注入 → 探针，全离线；
· **现场组**（本地有真库 + Ollama 才跑，否则 skip）：自动拷一份真库跑 H1/H3/H0 与总闸，
  不需要手动拷数据。CI 里没有那张图，自动跳过。
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import socket
import tempfile
from pathlib import Path

import networkx as nx
import pytest

from graphkb.memory_api import DEFAULT_MAX_CONTEXT_TOKENS, build_answer_context
from graphkb.query import query
from graphkb.triggers import EntityProbe

FIXTURE = Path(__file__).parent / "fixtures" / "realgraph"
GRAPH_FILE = "graph_chunk_entity_relation.graphml"

pytestmark = pytest.mark.skipif(
    not (FIXTURE / "manifest.json").is_file(),
    reason="没有真图夹具（先跑 scripts/capture_real_fixture.py）",
)


# ---------------------------------------------------------------- 夹具装载


def _manifest() -> dict:
    return json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


def _graph() -> nx.Graph:
    return nx.read_graphml(str(FIXTURE / GRAPH_FILE))


def _case(name: str) -> dict:
    retrieval = json.loads((FIXTURE / f"case_{name}.retrieval.json").read_text(encoding="utf-8"))
    vdb = json.loads((FIXTURE / f"case_{name}.vdb.json").read_text(encoding="utf-8"))
    return {"retrieval": retrieval, "vdb": vdb}


def _case_texts(name: str) -> dict:
    for case in _manifest()["cases"]:
        if case["name"] == name:
            return case
    raise AssertionError(f"manifest 里没有 case {name}")


class _GraphStorage:
    """最小图存储：形状与 LightRAG 的 `get_all_nodes` / `get_all_edges` 一致。"""

    def __init__(self, graph: nx.Graph):
        self._g = graph

    async def get_all_nodes(self):
        return [
            {
                "entity_id": n,
                "entity_type": d.get("entity_type") or d.get("type"),
                "description": d.get("description") or "",
                "source_id": d.get("source_id") or "",
                "file_path": d.get("file_path") or "",
            }
            for n, d in self._g.nodes(data=True)
        ]

    async def get_all_edges(self):
        return [
            {
                "source": u,
                "target": v,
                "description": d.get("description") or "",
                "keywords": d.get("keywords") or "",
                "weight": d.get("weight"),
            }
            for u, v, d in self._g.edges(data=True)
        ]


class _Vdb:
    def __init__(self, results: list):
        self._results = results

    async def query(self, question, top_k):
        return copy.deepcopy(self._results)


class _ReplayRag:
    """回放真实检索返回：除了读夹具，什么也不做，尤其不调 LLM。"""

    def __init__(self, case: dict, graph: nx.Graph):
        self.entities_vdb = _Vdb(case["vdb"])
        self.chunk_entity_relation_graph = _GraphStorage(graph)
        self._retrieval = case["retrieval"]

    async def aquery_data(self, question, param):
        return copy.deepcopy(self._retrieval)

    async def aquery(self, question, param):  # pragma: no cover - 走到就是用例写错了
        raise AssertionError("真图回归不该生成答案：Agent 面用 generate_answer=False")


def _run_case(name: str):
    graph = _graph()
    texts = _case_texts(name)
    rag = _ReplayRag(_case(name), graph)
    result = asyncio.run(
        query(
            rag,
            texts["question"],
            anchor_text=texts["anchor_text"],
            evidence_text=texts["evidence_text"],
            generate_answer=False,
        )
    )
    return graph, result


def _layers(trace: dict) -> dict[str, str]:
    return {e["name"]: e["layer"] for e in trace["entities"]}


# ---------------------------------------------------------------- 夹具本身


def test_fixture_is_sanitized_and_real_shaped():
    """夹具要「像真图」且「不含真内容」：规模够、描述非空、名字已脱敏。"""
    manifest = _manifest()
    assert manifest["sanitized"] is True, "公开仓库里只能放脱敏夹具（--raw 只供本地）"
    graph = _graph()
    sizes = manifest["fixture_graph"]

    assert sizes["nodes"] >= 50, "太小就压不出真图的问题（中间节点/预算/探针规模）"
    assert sizes["edges"] >= sizes["nodes"], "边比点还少就不是真图那种密度"
    assert graph.number_of_nodes() == sizes["nodes"]
    assert sizes["nodes_without_description"] == 0, "空描述会让「裸名字」缺陷假阳性"

    names = [str(n) for n in graph.nodes]
    assert len(set(names)) == len(names)
    assert any("." in n for n in names), "要留下带点号的名字（memory.search 那种形态）"
    assert all(n.startswith(("条目", "symbol_", "part")) for n in names), names[:5]


def test_fixture_descriptions_keep_sep_structure():
    """`<SEP>` 拼接的长描述是真实密度问题的来源，夹具必须留着这个形态。"""
    graph = _graph()
    joined = [d["description"] for _n, d in graph.nodes(data=True) if "<SEP>" in (d.get("description") or "")]
    assert joined, "夹具里应当有 <SEP> 拼接的多段描述"
    assert max(len(d) for d in joined) > 200


# ---------------------------------------------------------------- 分层（_hit_trace）


@pytest.mark.parametrize("case", ["h1_plan", "h0_named"])
def test_layers_on_real_graph(case):
    graph, result = _run_case(case)
    trace = result.trace
    assert result.trace_hit is True, "真实检索有命中，分层不该退化成空"
    names = set(str(n) for n in graph.nodes)

    layers = _layers(trace)
    assert layers, "至少要有锚点"
    assert set(layers.values()) <= {"anchor", "cited", "path"}
    assert set(layers) <= names, "命中集不能跑到图外（跑出去就是拿上下文之外的东西给人看）"
    assert sum(1 for v in layers.values() if v == "anchor") >= 1

    for rel in trace["relationships"]:
        assert layers.get(rel["src"]) is not None
        assert layers.get(rel["tgt"]) is not None
        assert rel["layer"] in {"direct", "path"}


def test_paths_are_consistent():
    """路径上「既不是锚点也不是引用点」的中间节点必须是 path 层；锚点自己占优。"""
    _graph_obj, result = _run_case("h1_plan")
    trace = result.trace
    layers = _layers(trace)
    hit = set(layers)
    anchors = set(trace["hit_layers"]["anchors"])
    cited = set(trace["hit_layers"]["cited"])

    assert trace["hit_layers"]["paths"], "真图上锚点之间应当能连出路径"
    middles = []
    for entry in trace["hit_layers"]["paths"]:
        assert entry["from"] in hit and entry["to"] in hit
        assert entry["hops"] >= 1
        for path in entry["paths"]:
            assert path[0] == entry["from"] and path[-1] == entry["to"]
            for mid in path[1:-1]:
                assert mid in hit, f"路径上的 {mid} 没进命中集"
                if mid in anchors:
                    assert layers[mid] == "anchor", "锚点优先于 path"
                elif mid in cited:
                    assert layers[mid] == "cited"
                else:
                    assert layers[mid] == "path", f"中间节点 {mid} 应标 path，实际 {layers[mid]}"
                    middles.append(mid)
    assert middles, "这个 case 的意义就在于有中间节点（否则压不出属性缺失的缺陷）"


def test_single_anchor_does_not_fabricate_paths():
    """只有一个锚点、没有引用点时，连不出路径就连不出——不许拿邻居充数。"""
    _graph_obj, result = _run_case("h0_named")
    trace = result.trace
    assert len(trace["hit_layers"]["anchors"]) == 1
    assert trace["hit_layers"]["cited"] == []
    assert trace["hit_layers"]["paths"] == []
    assert trace["relationships"] == []
    assert set(_layers(trace).values()) == {"anchor"}


def test_no_entity_lost_attributes_on_real_graph():
    """真图上曾经出现过「[path] MVP」这种裸名字段：路径中间节点必须带类型和描述。

    这是真图回归的核心断言——中间节点通常不在向量召回的上下文里，
    属性只能回图取。
    """
    graph, result = _run_case("h1_plan")
    nodes = {str(n): d for n, d in graph.nodes(data=True)}

    for entity in result.trace["entities"]:
        node = nodes.get(entity["name"]) or {}
        expected_type = node.get("entity_type") or node.get("type")
        if expected_type:
            assert entity.get("type") == expected_type, f"{entity['name']} 的类型没从图上取到"
        if (node.get("description") or "").strip():
            assert entity.get("description"), f"{entity['name']} 的描述没从图上取到"


def test_replay_is_deterministic():
    _g1, first = _run_case("h1_plan")
    _g2, second = _run_case("h1_plan")
    assert _layers(first.trace) == _layers(second.trace)
    assert first.trace["hit_layers"]["paths"] == second.trace["hit_layers"]["paths"]


# ---------------------------------------------------------------- 注入（Inline & Spill）


def _bundle(result, max_tokens: int):
    trace = result.trace
    return build_answer_context(
        trace["entities"], trace["relationships"], [], max_tokens
    )


@pytest.mark.parametrize("case", ["h1_plan"])
def test_injection_lines_are_never_bare_names(case):
    """注入里每一行都得说清「是什么」：类型 + 描述，不能只剩名字。"""
    _graph_obj, result = _run_case(case)
    bundle = _bundle(result, DEFAULT_MAX_CONTEXT_TOKENS)
    assert bundle.text

    lines = [ln for ln in bundle.text.splitlines() if ln.strip()]
    entity_lines = [ln for ln in lines if " -> " not in ln]
    assert entity_lines
    for line in entity_lines:
        assert "（" in line, f"没有类型：{line}"
        assert "：" in line, f"没有描述：{line}"


def test_injection_respects_budget_and_accounts_every_item():
    """预算是硬上限；装不下的进 spill，不许悄悄丢。"""
    _graph_obj, result = _run_case("h1_plan")
    tight = _bundle(result, 200)
    assert tight.used_tokens <= 200
    assert tight.spill_refs, "真图的描述很长，200 token 一定装不下全部"
    assert tight.spilled_tokens == sum(ref["tokens"] for ref in tight.spill_refs)

    refs = [ref["ref"] for ref in tight.spill_refs]
    assert len(refs) == len(set(refs)), "spill 引用不能重复"
    assert all(ref.startswith(("entity:", "relation:", "chunk:")) for ref in refs)

    roomy = _bundle(result, 100000)
    assert roomy.spill_refs == []
    assert roomy.used_tokens <= 100000
    assert roomy.inline_count >= tight.inline_count


def test_injection_on_real_graph_saturates_realistically():
    """真图的现实是「800 token 装不完」：这条钉住这个事实，免得以后悄悄变小又没人发现。"""
    _graph_obj, result = _run_case("h1_plan")
    bundle = _bundle(result, DEFAULT_MAX_CONTEXT_TOKENS)
    total_items = len(result.trace["entities"]) + len(result.trace["relationships"])
    assert bundle.inline_count < total_items, "如果一次就装下了，说明夹具退化成小图了"
    assert bundle.used_tokens > DEFAULT_MAX_CONTEXT_TOKENS * 0.6


# ---------------------------------------------------------------- 探针


def test_probe_loads_real_scale_names():
    graph = _graph()
    probe = EntityProbe([str(n) for n in graph.nodes])
    texts = _case_texts("h1_plan")

    hit = probe.match(texts["anchor_text"])
    assert hit, "锚文本里的实体名应当被探到"
    assert all(name in graph for name in hit)

    # 长名优先：图上同时有「X」和「X 的后缀」时，不能把长的切成短的
    names = sorted((str(n) for n in graph.nodes), key=len, reverse=True)
    longest = names[0]
    assert probe.match(f"这里提到 {longest} 一下")[0] == longest


def test_probe_ignores_off_topic_text():
    graph = _graph()
    probe = EntityProbe([str(n) for n in graph.nodes])
    assert probe.match("今天天气不错，把桌面上的文件归档一下") == []


# ---------------------------------------------------------------- 现场组（真库）


def _ollama_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.3):
            return True
    except OSError:
        return False


REAL_WORKSPACE = Path(
    os.environ.get("GKB_REAL_WORKSPACE", r"C:\Users\fjibj\cola\outputs\gk-probe\probe-data")
)


@pytest.mark.slow
@pytest.mark.skipif(
    not (REAL_WORKSPACE / GRAPH_FILE).is_file() or not _ollama_up(),
    reason="现场组需要真实 workspace 与本地 Ollama（CI 里没有，自动跳过）",
)
def test_live_real_workspace_end_to_end(tmp_path):
    """拿真库跑一遍读侧：探针 → H1 → 离题 H3 → H0，全程只读（自己拷一份，不碰原件）。"""
    from dotenv import load_dotenv

    from graphkb.config import load_config
    from graphkb.memory_api import MemoryTools
    from graphkb.rag import init_rag
    from graphkb.triggers import SessionGate, TriggerEngine

    load_dotenv()
    ws = tmp_path / "ws"
    shutil.copytree(REAL_WORKSPACE, ws)

    cfg = load_config()
    cfg.working_dir = str(ws)

    async def scenario() -> dict:
        rag = await init_rag(cfg)
        try:
            probe = EntityProbe()
            size = await probe.refresh(rag)
            engine = TriggerEngine(
                search=MemoryTools(cfg, rag).search,
                probe=probe,
                gate=SessionGate(cfg.triggers.autonomous_limit),
            )
            names = sorted([name async for name in _names_of(rag)], key=len, reverse=True)
            anchors = " ".join(names[:3])
            plan = await engine.on_plan(f"帮我整理{anchors}这几件事，写进说明")
            off = await engine.on_context("今天天气不错，把桌面上的文件归档一下")
            named = await engine.on_named(f"{names[0]} 是什么")
            return {
                "size": size,
                "names": names,
                "plan": plan,
                "off": off,
                "named": named,
                "gate_used": engine.gate.used,
            }
        finally:
            await rag.finalize_storages()

    async def _names_of(rag):
        for node in await rag.chunk_entity_relation_graph.get_all_nodes():
            name = node.get("entity_id") or node.get("id")
            if name:
                yield str(name)

    out = asyncio.run(scenario())

    assert out["size"] >= 200, f"真库应当有上百个实体名，实际 {out['size']}"
    assert out["plan"].event.queried is True
    assert out["plan"].event.hit is True
    ctx = (out["plan"].result or {}).get("answer_context") or ""
    assert ctx
    for line in ctx.splitlines():
        if line.startswith(("[anchor]", "[cited]", "[path]")) and " -> " not in line:
            assert "（" in line and "：" in line, f"注入里出现裸名字：{line}"
    assert out["off"].event.queried is False and out["off"].event.skipped == "no_entity"
    assert out["named"].event.queried is True and out["named"].event.exempt is True
