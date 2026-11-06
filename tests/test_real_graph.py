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

from graphkb.config import Config
from graphkb.memory_api import DEFAULT_MAX_CONTEXT_TOKENS, MemoryTools, build_answer_context
from graphkb.provenance import annotate
from graphkb.query import query
from graphkb.triggers import EntityProbe, SessionGate, TriggerEngine

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


def _chunks() -> dict:
    path = FIXTURE / "text_chunks.json"
    if not path.is_file():
        pytest.skip("夹具里没有 text_chunks.json（先跑 scripts/capture_real_fixture.py --chunks-only）")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture_chunks() -> dict:
    return _chunks()


def _replay(
    case: str,
    *,
    question: str | None = None,
    anchor_text: str | None = None,
    evidence_text: str | None = None,
    answer: str | None = None,
    generate_answer: bool = False,
):
    """拿真图夹具回放一次，参数可换（M1 就靠换文本验证双文本分离）。"""
    graph = _graph()
    texts = _case_texts(case)
    rag = _ReplayRag(_case(case), graph, _chunks(), answer=answer)
    result = asyncio.run(
        query(
            rag,
            question or texts["question"],
            anchor_text=anchor_text if anchor_text is not None else texts["anchor_text"],
            evidence_text=evidence_text if evidence_text is not None else texts["evidence_text"],
            generate_answer=generate_answer,
        )
    )
    return graph, result


def _retrieved_names(result) -> list[str]:
    return [str(n) for n in (result.trace.get("retrieved") or {}).get("entities") or []]


def _pick_three(result, graph=None) -> tuple[str, str, str]:
    """从真实检索结果里挑三个「在图上、互不为子串」的实体名，用来造「锚点 ≠ 证据」的文本。"""
    nodes = {str(n) for n in graph.nodes} if graph is not None else None
    names = [
        n for n in _retrieved_names(result) if len(n) >= 4 and (nodes is None or n in nodes)
    ]
    picked: list[str] = []
    for n in names:
        if all(n not in o and o not in n for o in picked):
            picked.append(n)
        if len(picked) == 3:
            return picked[0], picked[1], picked[2]
    raise AssertionError(f"真图检索结果里挑不出三个实体名：{names[:6]}")


def _tools(rag) -> MemoryTools:
    """M2/M3 的落点。预算用默认值（不读本地 .env，免得回归跟着环境漂）。"""
    return MemoryTools(Config(), rag)


def _engine(rag, *, gate: int = 5) -> TriggerEngine:
    probe = EntityProbe([str(n) for n in _graph().nodes])
    return TriggerEngine(search=_tools(rag).search, probe=probe, gate=SessionGate(gate))


class _GraphStorage:
    """最小图存储：形状与 LightRAG 的 `get_all_nodes` / `get_all_edges` / `get_node` / `get_edge` 一致。

    `get_node` / `get_edge` 是 M3（`memory.expand`）与 M4（溯源）要用的单条读，
    少一个就会在真图回归里退化成 `missing`——那种“全缺失”看着像夹具问题，实际是接口没对齐。
    """

    def __init__(self, graph: nx.Graph):
        self._g = graph

    def _node(self, name: str) -> dict | None:
        if name not in self._g:
            return None
        d = self._g.nodes[name]
        return {
            "entity_id": name,
            "entity_type": d.get("entity_type") or d.get("type"),
            "description": d.get("description") or "",
            "source_id": d.get("source_id") or "",
            "file_path": d.get("file_path") or "",
        }

    async def get_all_nodes(self):
        return [self._node(str(n)) for n in self._g.nodes]

    async def get_node(self, name):
        return copy.deepcopy(self._node(str(name)))

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

    async def get_edge(self, src, tgt):
        src, tgt = str(src), str(tgt)
        for u, v in ((src, tgt), (tgt, src)):  # 夹具图是无向的，两边都试（与 LightRAG 一致）
            if self._g.has_edge(u, v):
                d = self._g.edges[u, v]
                return {
                    "src_id": u,
                    "tgt_id": v,
                    "description": d.get("description") or "",
                    "keywords": d.get("keywords") or "",
                    "weight": d.get("weight"),
                    "source_id": d.get("source_id") or "",
                    "file_path": d.get("file_path") or "",
                }
        return None


class _TextChunks:
    """块存储：`text_chunks.json` 里那几块原文，接口与 `JsonKVStorage` 对齐。"""

    def __init__(self, rows: dict):
        self._rows = rows

    async def get_by_id(self, chunk_id):
        return copy.deepcopy(self._rows.get(str(chunk_id)))

    async def get_by_ids(self, chunk_ids):
        return [copy.deepcopy(self._rows.get(str(c))) for c in chunk_ids]


class _Vdb:
    def __init__(self, results: list):
        self._results = results

    async def query(self, question, top_k):
        return copy.deepcopy(self._results)


class _ReplayRag:
    """回放真实检索返回：除了读夹具，什么也不做，尤其不调 LLM。

    `answer` 只有人类面用例才给：Agent 面一律 `generate_answer=False`，
    要是真调了 `aquery` 就说明分层又退回依赖 LLM 答案的者路子，直接报错。
    """

    def __init__(self, case: dict, graph: nx.Graph, chunks: dict | None = None, answer: str | None = None):
        self.entities_vdb = _Vdb(case["vdb"])
        self.chunk_entity_relation_graph = _GraphStorage(graph)
        self.text_chunks = _TextChunks(chunks or {})
        self._retrieval = case["retrieval"]
        self._answer = answer

    async def aquery_data(self, question, param):
        return copy.deepcopy(self._retrieval)

    async def aquery(self, question, param):
        if self._answer is None:
            raise AssertionError("真图回归不该生成答案：Agent 面用 generate_answer=False")
        return self._answer


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
    """注入里每一行都得说清「是什么」：至少要带类型（path 层不要求描述，这是按层分预算的选择）。

    path 行只负责证明「锚点和引用点连得上」，带类型 + 名字就够；要描述用 `entity:` 取。
    真正要防的是「[path] MVP」那种连类型都没有的裸名字。
    """
    _graph_obj, result = _run_case(case)
    bundle = _bundle(result, DEFAULT_MAX_CONTEXT_TOKENS)
    assert bundle.text

    lines = [ln for ln in bundle.text.splitlines() if ln.strip()]
    entity_lines = [ln for ln in lines if " -> " not in ln and not ln.startswith("[chunk]")]
    assert entity_lines
    for line in entity_lines:
        assert "（" in line, f"没有类型：{line}"
        if line.startswith("[path]"):
            assert "：" not in line, f"path 层不该带描述（省额度）：{line}"
        else:
            assert "：" in line, f"锚点/引用点没有描述：{line}"


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


# ================================================================ M1 双文本判据


def test_m1_anchor_and_evidence_are_separated():
    """锚点只认 anchor_text、证据只认 evidence_text：同一张图、同一份检索，换文本就换分层。

    这是 M1 的立命之本。小图上“问题里没名字、任务里有名字”很容易成立，
    真图上才看得出两边会不会糊到一起（比如短名被长名吃掉、名字根本不在图上）。
    """
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)

    _g, result = _replay(
        "h1_plan", anchor_text=f"{a} 是什么", evidence_text=f"帮我核对 {b} 和 {c} 的接口说明"
    )
    layers = result.trace["hit_layers"]
    assert layers["anchor_mode"] == "literal"
    assert layers["anchors"] == [a], "锚点只能来自 anchor_text"
    assert set(layers["cited"]) == {b, c}, "证据只能来自 evidence_text"
    assert a not in layers["cited"]
    # 引用点要不连上锚点（paths），要不被明说连不上（disconnected）——不能两边都不沾
    assert len(layers["paths"]) + len(layers["disconnected"]) >= 1


class _AnswerRag(_ReplayRag):  # 只是给人类面用例取个名字，构造见 _ReplayRag
    pass


def test_m1_human_face_takes_evidence_from_answer():
    """人类面不变：anchor=问题、evidence=那次生成的答案（答案里提到的实体才上证据层）。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    answer = f"{b} 和 {c} 都挂在 {a} 下面。"
    rag = _AnswerRag(_case("h1_plan"), graph, _chunks(), answer=answer)
    result = asyncio.run(query(rag, a, anchor_text=a, generate_answer=True))
    layers = result.trace["hit_layers"]
    assert layers["anchors"] == [a]
    assert set(layers["cited"]) == {b, c}


def test_m1_equal_texts_rejected_on_real_graph():
    """两参相等一律抛错：相等时 cited 必空、paths 退化成锚点全排列噪声。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    same = f"帮我核对 {a} 和 {b}"
    with pytest.raises(ValueError, match="不能相等"):
        _replay("h1_plan", anchor_text=same, evidence_text=same)


def test_m1_agent_face_never_generates_answer():
    """Agent 面一次 LLM 答案都不该花：`_ReplayRag(answer=None)` 一被 aquery 就炸。"""
    _graph_obj, result = _replay("h1_plan")
    assert result.answer == ""
    assert result.trace_hit is True


def test_m1_missing_evidence_rejected():
    graph = _graph()
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    with pytest.raises(ValueError, match="evidence_text"):
        asyncio.run(query(rag, "真图上的任意一问", generate_answer=False))


# ================================================================ M2 记忆面（memory.search）


def _search(rag, *, task: str, query_text: str | None = None, budget: dict | None = None, mode: str = "agent"):
    return asyncio.run(_tools(rag).search({"query": query_text or "", "task": task}, budget, mode))


def test_m2_search_shape_on_real_graph():
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())

    res = _search(rag, query_text=a, task=f"帮我核对 {b} 和 {c} 的接口说明，写进 {a} 的文档")
    assert res["version"] == "1"
    assert res["mode"] == "agent"
    # 真图的现实：默认 800 token 装不完（后面 test_m2_real_graph_budget_is_the_bottleneck 专门铉住）
    assert res["reason"] in {None, "budget_truncated"}
    assert res["degraded"] is bool(res["spill_refs"]) or res["degraded"] is False
    assert res["trace"]["anchors"] == [a]
    assert set(res["trace"]["cited"]) >= {b, c}
    assert res["answer_context"]

    used = res["trace"]["budget_used"]
    assert used["context_tokens"] == DEFAULT_MAX_CONTEXT_TOKENS
    assert used["context_used"] <= DEFAULT_MAX_CONTEXT_TOKENS
    assert res["trace"]["retrieved"]["entity_count"] >= 1

    for item in res["hits"]["entities"] + res["hits"]["relationships"]:
        assert item["origin"] in {"extracted", "manual", "mixed", "unknown"}
        assert set(item["provenance"]) >= {
            "manual",
            "docs",
            "doc_ids",
            "chunk_ids",
            "chunks",
            "unresolved",
        }


def test_m2_texts_equal_degrades_on_real_graph():
    """query 缺省 → 锚点与证据同一段文本 → 如实降级成 human 语义，而不是喑着骗。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    answer = f"{b} 和 {c} 都挂在 {a} 下面。"
    rag = _AnswerRag(_case("h1_plan"), graph, _chunks(), answer=answer)

    res = _search(rag, task=f"帮我核对 {b} 和 {c} 的接口说明")
    assert res["mode"] == "human"
    assert res["reason"] == "texts_equal"
    assert res["degraded"] is True
    assert any("退回人类面语义" in w for w in res["warnings"]), res["warnings"]
    assert set(res["trace"]["anchors"]) == {b, c}  # 人类面：锚点取任务里的字面名


def test_m2_unlinked_chunks_stay_out_of_injection():
    """真图必然有「话题相似但实体无关」的块：它们留在 hits 里、标 linked=false，但不进注入。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())

    res = _search(rag, query_text=a, task=f"帮我核对 {b} 和 {c} 的接口说明")
    flags = [c_["linked"] for c_ in res["hits"]["chunks"]]
    assert flags, "真图检索返回里应当带块"
    assert any(f is False for f in flags), "真图上必然有无来源交集的块（否则这条用例白写）"
    assert any("没有来源交集" in w for w in res["warnings"])

    linked_ids = {
        str(c_["chunk_id"])
        for c_ in res["hits"]["chunks"]
        if c_["linked"] is True
    }
    for ref in res["spill_refs"]:
        if ref["kind"] == "chunk":
            assert ref["ref"].split(":", 1)[1] in linked_ids, "没关联的块不许出现在注入/溢出清单里"


def test_m2_real_graph_injection_is_dominated_by_path_nodes():
    """真图上注入的行数仍由路径节点占多数，但**额度**现在被它们省下来了。

    1 个锚 + 2 个引用点 → 10 行 path：行数过半，token 却只占一两成——
    这就是按层分预算想要的效果（行数不是问题，额度才是）。
    """
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())

    res = _search(rag, query_text=a, task=f"帮我核对 {b} 和 {c} 的接口说明")
    lines = [ln for ln in res["answer_context"].splitlines() if ln.startswith("[")]
    layers = [ln.split("]")[0] + "]" for ln in lines]
    assert layers.count("[anchor]") == 1
    assert layers.count("[path]") > len(layers) / 2, f"path 行数应当过半：{layers}"

    by_layer = res["trace"]["budget_used"]["context_by_layer"]
    path_tokens = by_layer["path"]["tokens"]
    assert path_tokens <= res["trace"]["budget_used"]["context_used"] * 0.35, (
        f"path 层额度应当很小：{by_layer}"
    )
    for line in lines:
        if line.startswith("[path]"):
            assert "：" not in line, f"path 行不该带描述：{line}"


def test_m2_real_graph_overflow_lands_on_chunks():
    """按层分预算之后：图侧（实体/关系）全进得来，溢出全落在块上且可取回。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())

    res = _search(rag, query_text=a, task=f"帮我核对 {b} 和 {c} 的接口说明")
    assert res["reason"] == "budget_truncated"
    assert res["degraded"] is True
    used = res["trace"]["budget_used"]
    graph_items = len(res["hits"]["entities"]) + len(res["hits"]["relationships"])
    assert used["context_inline"] >= graph_items, "实体与关系应当全进得来（path 层省下的额度够用）"
    assert {r["kind"] for r in res["spill_refs"]} == {"chunk"}, "溢出应当只落在块上"
    for ref in res["spill_refs"]:
        assert ref["ref"].split(":", 1)[1] in {
            str(c_["chunk_id"]) for c_ in res["hits"]["chunks"]
        }


def test_m2_budget_truncated_is_overflow_not_drop():
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())

    res = _search(
        rag,
        query_text=a,
        task=f"帮我核对 {b} 和 {c} 的接口说明",
        budget={"max_context_tokens": 150},
    )
    assert res["reason"] == "budget_truncated"
    assert res["degraded"] is True
    assert res["spill_refs"]
    used = res["trace"]["budget_used"]
    assert used["context_tokens"] == 150
    assert used["context_used"] <= 150
    assert used["context_spilled"] == len(res["spill_refs"])
    assert used["spilled_tokens"] == sum(r["tokens"] for r in res["spill_refs"])


def test_m2_no_anchor_falls_back_honestly():
    """离题文本：问题里没有字面实体名 → 锚点靠向量兜底或干脆不分层，两种都要说出来。"""
    graph = _graph()
    rag = _AnswerRag(_case("h1_plan"), graph, _chunks(), answer="")
    res = _search(rag, task="今天天气不错，把桌面上的文件归档一下", mode="human")
    assert res["trace"]["anchor_mode"] in {"vector_fallback", "none"}
    assert res["degraded"] is True
    assert res["reason"] in {"vector_fallback", "no_anchor"}
    assert res["warnings"]


# ================================================================ M3 Inline & Spill + expand


def test_m3_spill_then_expand_roundtrip():
    """溢出不是丢弃：spill 里的引用能按图/块存储取回，不用进程内缓存。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    tools = _tools(rag)

    res = asyncio.run(
        tools.search(
            {"query": a, "task": f"帮我核对 {b} 和 {c} 的接口说明"}, {"max_context_tokens": 150}
        )
    )
    refs = [r["ref"] for r in res["spill_refs"]]
    assert refs, "真图长描述 + 150 token 预算，必然溢出"

    out = asyncio.run(tools.expand(refs))
    assert out["missing"] == [], f"夹具里的引用应当都取得到：{out['missing']}"
    assert len(out["items"]) == len(refs)
    assert "entity" in {i["kind"] for i in out["items"]}
    for item in out["items"]:
        assert item["text"] and item["tokens"] >= 1
        assert item["origin"] in {"extracted", "manual", "mixed", "unknown"}


def test_m3_expand_reports_missing_with_reasons():
    graph = _graph()
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    out = asyncio.run(
        _tools(rag).expand(
            ["entity:图里根本没有的实体", "relation:只有一端", "chunk:没有这块", "what:乱写"]
        )
    )
    assert out["items"] == []
    assert len(out["missing"]) == 4
    assert all(m["reason"] for m in out["missing"])


def test_m3_expand_truncates_and_caps():
    graph = _graph()
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    name = sorted((str(n) for n in graph.nodes), key=len, reverse=True)[0]
    ref = f"entity:{name}"

    out = asyncio.run(_tools(rag).expand([ref], 1))
    assert out["items"][0]["truncated"] is True
    assert out["items"][0]["text"].endswith("…")

    with pytest.raises(ValueError, match="一次最多"):
        asyncio.run(_tools(rag).expand([ref] * 21))


# ================================================================ M4 溯源标签


def _node_records(graph: nx.Graph) -> list[dict]:
    return [
        {"source_id": d.get("source_id") or "", "file_path": d.get("file_path") or ""}
        for _n, d in graph.nodes(data=True)
    ]


def test_m4_real_nodes_are_extracted_and_resolve_docs():
    """真图全是从文档抽取的：origin 恒为 extracted，且能顺着块反查到 4 篇来源文档。"""
    graph = _graph()
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    provs = asyncio.run(annotate(rag, _node_records(graph)))

    assert {p.origin for p in provs} == {"extracted"}
    assert all(p.chunk_ids for p in provs), "每个节点都该说得出是哪几块里抽出来的"
    assert all(p.docs for p in provs), "块存储查得到，来源文档就不该为空"
    assert sum(p.unresolved for p in provs) == 0
    assert not any(p.manual for p in provs)
    assert len({d for p in provs for d in p.doc_ids}) >= 2, "真图来自多篇文档，不该只剩一篇"


def test_m4_manual_and_mixed_marks_on_real_copy():
    """在真图副本上打上两个版本的手工痕迹，origin 得同时认两种形态。"""
    graph = _graph()
    names = [str(n) for n in graph.nodes]
    graph.nodes[names[0]]["source_id"] = "manual_creation"  # 1.5.6 形态
    graph.nodes[names[1]]["source_id"] = ""  # 1.5.7 关系形态
    graph.nodes[names[1]]["file_path"] = "manual_creation"
    graph.nodes[names[2]]["source_id"] = (
        str(graph.nodes[names[2]].get("source_id") or "") + "<SEP>manual_creation"
    )

    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    provs = asyncio.run(annotate(rag, _node_records(graph)))
    by_name = dict(zip(names, provs))
    assert by_name[names[0]].origin == "manual"
    assert by_name[names[1]].origin == "manual"
    assert by_name[names[2]].origin == "mixed"
    assert by_name[names[2]].manual is True


def test_m4_search_and_expand_carry_provenance():
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    tools = _tools(rag)

    res = asyncio.run(tools.search({"query": a, "task": f"帮我核对 {b} 和 {c}"}))
    for item in res["hits"]["entities"] + res["hits"]["relationships"]:
        assert item["provenance"]["chunks"] >= 0

    out = asyncio.run(tools.expand([f"entity:{a}"]))
    assert out["items"][0]["origin"] == "extracted"
    assert out["items"][0]["provenance"]["docs"]


# ================================================================ M5 触发器


def test_m5_h1_on_real_names():
    """真图 80 个名字挂在探针上：起手查靠字面命中，不靠向量相似度。"""
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    engine = _engine(rag, gate=5)

    out = asyncio.run(engine.on_plan(f"帮我整理 {a} 的设计，重点核对 {b} 的预算"))
    assert out.event.hook == "H1"
    assert out.event.queried is True
    assert out.event.entities == [a, b]
    assert out.event.hit is True
    # 真图上 800 token 装不完 → 溢出是常态（与 test_m2_real_graph_budget_is_the_bottleneck 一致）
    assert out.event.degraded is True
    assert out.event.reason == "budget_truncated"
    assert out.event.spill and out.event.spill >= 1
    assert out.event.gate_left == 4
    assert out.event.context_tokens and out.event.context_tokens <= DEFAULT_MAX_CONTEXT_TOKENS


def test_m5_h2_and_h3_on_real_names():
    graph, base = _replay("h1_plan")
    a, b, c = _pick_three(base, graph)
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    engine = _engine(rag)

    stuck = asyncio.run(engine.on_stuck(f"KeyError: {a} 的 join_date 字段缺失"))
    assert stuck.event.hook == "H2"
    assert stuck.event.entities == [a]
    assert stuck.event.queried is True

    recall = asyncio.run(engine.on_context(f"刚才那段说明里 {b} 的预算好像算错了"))
    assert recall.event.hook == "H3"
    assert recall.event.entities == [b]
    assert recall.event.queried is True


def test_m5_offtopic_skips_and_gate_holds_on_real_graph():
    graph = _graph()
    names = sorted((str(n) for n in graph.nodes if len(str(n)) >= 4), key=len)
    a = names[0]
    rag = _ReplayRag(_case("h1_plan"), graph, _chunks())
    engine = _engine(rag, gate=2)

    off = asyncio.run(engine.on_context("今天天气不错，把桌面上的文件归档一下"))
    assert off.event.queried is False
    assert off.event.skipped == "no_entity"
    assert engine.gate.used == 0, "探不到实体不扣格"

    for _ in range(2):
        spent = asyncio.run(engine.on_plan(f"帮我整理 {a} 的设计"))
        assert spent.event.queried is True

    blocked = asyncio.run(engine.on_plan(f"帮我整理 {a} 的设计"))
    assert blocked.event.queried is False
    assert blocked.event.skipped == "gate_exhausted"

    named = asyncio.run(engine.on_named(a))
    assert named.event.queried is True and named.event.exempt is True
    assert len(engine.trace()) == 5


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
    # 这里故意用 workspace=""（与其它测试实例同 workspace）：就是要让自动隔离过一遍。
    # LightRAG 的 KV 挂在进程级共享字典上，同 workspace 不同目录的第二实例本来会
    # “图读得到 260 个节点、块全查不到”；`rag.init_rag` 里的脱钩就是冲这个去的。
    ws = tmp_path / "ws"
    shutil.copytree(REAL_WORKSPACE, ws)

    cfg = load_config()
    cfg.working_dir = str(ws)
    cfg.workspace = ""

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

            # M2：真库上跑一次 search（小预算强制溢出），看记账与降级
            tools = MemoryTools(cfg, rag)
            search = await tools.search(
                {"query": names[0], "task": f"帮我整理 {names[1]} 和 {names[2]} 的说明"},
                {"max_context_tokens": 200},
            )
            # M3：溢出的引用无状态取回（实体 / 关系 / 块都在 refs 里）
            refs = [r["ref"] for r in search["spill_refs"]][:20]
            expanded = await tools.expand(refs) if refs else {"items": [], "missing": []}
            # M4：全图溯源的 origin 分布
            provs = await annotate(
                rag,
                [
                    {"source_id": n.get("source_id") or "", "file_path": n.get("file_path") or ""}
                    for n in await rag.chunk_entity_relation_graph.get_all_nodes()
                ],
            )
            return {
                "size": size,
                "names": names,
                "plan": plan,
                "off": off,
                "named": named,
                "gate_used": engine.gate.used,
                "search": search,
                "expanded": expanded,
                "refs": refs,
                "provs": provs,
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
            assert "（" in line, f"注入里出现裸名字：{line}"
            if not line.startswith("[path]"):
                assert "：" in line, f"锚点/引用点没有描述：{line}"
    assert out["off"].event.queried is False and out["off"].event.skipped == "no_entity"
    assert out["named"].event.queried is True and out["named"].event.exempt is True

    # M2：真库上的 search 既要给得出注入内容，也要老实报溢出
    search = out["search"]
    assert search["answer_context"]
    assert search["reason"] == "budget_truncated" and search["spill_refs"]
    assert search["trace"]["budget_used"]["context_used"] <= 200

    # M3：溢出的引用取得回（真库 + 真块存储，无进程内状态）
    assert out["expanded"]["items"], (
        f"refs={out['refs'][:5]} missing={out['expanded']['missing'][:5]}"
    )
    assert out["expanded"]["missing"] == [], out["expanded"]["missing"]

    # M4：真库的节点全是从文档抽的，且每个都说得出块（没有被删/改）
    origins = {p.origin for p in out["provs"]}
    assert origins == {"extracted"}, f"真库全是从文档抽的，出现 {origins} 说明判定错了"
    assert sum(p.unresolved for p in out["provs"]) == 0
