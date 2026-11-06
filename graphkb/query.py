"""检索问答：返回答案 + 结构化 trace（dual-level 命中：实体/关系/块 + 检索关键词）。

trace 即 S1 的"透明窗"数据源，S3 只负责渲染它，不再改检索逻辑。

硬约束（Failure Condition 1）：trace 为空时绝不返回黑盒答案——显式返回"未找到"，
不生成/不返回任何无据可查的答案。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from lightrag import QueryParam

from .config import RetrievalConfig

NOT_FOUND_ANSWER = "未找到相关实体（图中未命中任何实体或关系）。"


@dataclass
class QueryResult:
    question: str = ""
    answer: str = ""
    trace: dict = field(default_factory=dict)
    trace_hit: bool = False


def _build_trace(data: dict, metadata: dict) -> dict[str, Any]:
    entities = [
        {
            "name": e.get("entity_name"),
            "type": e.get("entity_type"),
            "description": e.get("description"),
        }
        for e in data.get("entities", [])
    ]
    relationships = [
        {
            "src": r.get("src_id"),
            "tgt": r.get("tgt_id"),
            "description": r.get("description"),
            "keywords": r.get("keywords"),
            "weight": r.get("weight"),
        }
        for r in data.get("relationships", [])
    ]
    chunks = [
        {"content": c.get("content"), "chunk_id": c.get("chunk_id")}
        for c in data.get("chunks", [])
    ]
    return {
        "query_mode": metadata.get("query_mode"),
        "keywords": metadata.get("keywords"),
        "entities": entities,
        "relationships": relationships,
        "chunks": chunks,
        # 检索器到底掳到了什么——不受后续分层/高亮影响的原记录，
        # 用来区分「检索没拿到」与「拿到了但答案没引用」
        "retrieved": {
            "entity_count": len(entities),
            "relation_count": len(relationships),
            "entities": [e["name"] for e in entities],
            "relationships": [f"{r['src']}->{r['tgt']}" for r in relationships],
        },
        "processing_info": metadata.get("processing_info"),
    }


def _safe_score(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Budget values are configurable now: GKB_HIT_TOP_K / GKB_MAX_HOPS / GKB_MAX_PATHS
# (see config.RetrievalConfig). This module keeps no numbers of its own — the single
# source of truth for defaults is config.py, so tests and server cannot drift apart.

LAYER_ORDER = {"anchor": 0, "cited": 1, "path": 2}


def _literal_names(text: str, names: Iterable[str]) -> list[str]:
    """返回在 text 里字面出现的实体名；长名优先，被长名包含的短名不重复计（「杰伦」不另计）。"""
    if not text:
        return []
    out: list[str] = []
    for n in sorted({str(x) for x in names if x}, key=lambda v: (-len(v), v)):
        if n in text and not any(n != o and n in o for o in out):
            out.append(n)
    return out


def _undirected_adjacency(edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """无向邻接表（弱连通语义：人看小图时不区分方向）。"""
    adj: dict[str, list[str]] = {}
    for s, t in edges:
        if not s or not t or s == t:
            continue
        adj.setdefault(s, [])
        adj.setdefault(t, [])
        if t not in adj[s]:
            adj[s].append(t)
        if s not in adj[t]:
            adj[t].append(s)
    return adj


def _shortest_paths(
    adj: dict[str, list[str]], src: str, dst: str, *, max_hops: int, max_paths: int
) -> list[list[str]]:
    """src→dst 的全部等长最短路（节点序列）。不可达或超过 max_hops → []。"""
    if src == dst:
        return [[src]]
    dist = {src: 0}
    preds: dict[str, list[str]] = {}
    queue = deque([src])
    while queue:
        u = queue.popleft()
        if dist[u] >= max_hops:
            continue
        for v in adj.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                preds[v] = [u]
                queue.append(v)
            elif dist[v] == dist[u] + 1 and u not in preds[v]:
                preds[v].append(u)
    if dst not in dist:
        return []
    paths: list[list[str]] = []
    stack = [[dst]]
    guard = 0
    while stack and guard < 2000:
        guard += 1
        p = stack.pop()
        u = p[0]
        if u == src:
            paths.append(list(p))
            continue
        for w in preds.get(u, ()):
            stack.append([w, *p])
    paths.sort()
    return paths[:max_paths]


async def _hit_trace(
    rag,
    anchor_text: str,
    evidence_text: str,
    trace: dict,
    budget: RetrievalConfig | None = None,
) -> dict:
    """把「检索器捞到什么」收敛成「答案落在哪条路径上」——三态分层，分数只作旁证。

    两块文本各管一段（M1 双文本改造，判据逻辑本身一行未改）：
      anchor_text   → 锚点：这段文本里字面出现的图实体名
      evidence_text → 证据：这段文本里字面引用的图实体名（+ 连接锚点的最短路）
    人问：anchor_text=问题、evidence_text=答案；
    Agent：anchor_text=context.query、evidence_text=context.task。

    为什么不用分数决定去留：实体向量库 embed 的是「名字+描述」，它只懂「话题相似」，
    不懂「问题问的是不是它」。问「腾讯总部在哪」时「字节跳动」（描述含“总部位于北京”）
    会进 top_k；问「蔡依林和周杰伦」时答案主语「台北」的比值正好卡在 0.80 边界——
    任何阈值都是运气，不是判据。所以取舍改由两个可调用的结构判据决定：

      锚点 = anchor_text 里字面出现的图实体名（零参数、可复算）
      证据 = evidence_text 里字面引用的图实体名 + 连接它们的最短路径（连通性由构造保证）
      仅召回 = 向量捞到但两者都不是 → 不着色，只在候选列表里带着分数展示

    一题的高亮因此是「若干连通簇」：对比题（「腾讯和字节跳动的总部」）天然得到两个簇，
    簇间无路径会被记进 disconnected 而不是被阈值抹掉——不连通本身就是答案的一部分。
    另将 ll_keywords 里图上查无此名的关键词记进 unmatched_keywords，用来分辨
    「检索没做好」与「图里本来就没这个实体」（如问「张三认识姚明吗」而姚明从未入库）。
    向量库异常 → 不猜锚点、不分层，原样退回上下文（score=None），绝不编造。

    两参相等一律报错（不警告、不降级）：相等时 evidence_text 里的每个实体必然也是锚点，
    `cited` 被锚点豁免成空，paths 只剩锚点两两全排列——探针 B §4 实测（8 个锚点）
    cited=[]、paths=28（C(8,2)）。那种状态下高亮照样上色、看着“正常”，但证据位已经死了，
    属于只会骗人的假信号。

    M2 约定（2026-11-04 拍板）：MCP 的 `memory.search` 把这条 ValueError 映射成
    `degraded=true / reason="texts_equal"` 返回给调用方，与 `vdb_error` 同一种处理——
    判据层保持硬失败，接口层负责把它翻译成可读的降级信号，不让 agent 吃到异常。
    """
    if anchor_text == evidence_text:
        raise ValueError(
            "anchor_text 与 evidence_text 不能相等"
            "（证据层会塌成空、paths 退化成锚点全排列噪声）；"
            "人问请传 (问题, 答案)，Agent 请传 (context.query, context.task)"
        )

    b = budget or RetrievalConfig()
    full_entities = trace.get("entities", [])
    full_relationships = trace.get("relationships", [])

    pool: list[str] = []
    for e in full_entities:
        name = str(e.get("name") or "")
        if name and name not in pool:
            pool.append(name)
    for r in full_relationships:
        for key in (str(r.get("src") or ""), str(r.get("tgt") or "")):
            if key and key not in pool:
                pool.append(key)

    keywords = trace.get("keywords", {}) or {}
    ll_kw = [str(k) for k in (keywords.get("low_level") or [])]
    query_text = ", ".join(ll_kw) if ll_kw else anchor_text
    # 问题抽出的低层关键词里，哪些在图上根本不存在——这跟「检索坏了」不是一回事，
    # 是图本身缺东西（没写过、或实体没对齐），得单独告知，不能闷在红圈里。
    # LLM 有时把短语（「张三的公司」）也当成低层关键词，这类能包回已匹配实体名的不当作缺实体。
    pool_set = set(pool)
    q_names = _literal_names(anchor_text, pool)
    unmatched = [
        k
        for k in ll_kw
        if k and k not in pool_set and not any(k == n or k in n or n in k for n in q_names)
    ]

    def _degrade(mode: str) -> dict:
        trace["entities"] = [{**e, "score": None, "layer": None} for e in full_entities]
        trace["relationships"] = [{**r, "score": None, "layer": None} for r in full_relationships]
        trace["hit_layers"] = _layers_shell(mode, unmatched, budget=b)
        return trace

    # 分数：只用来（a）问题里没有字面实体名时兜底选锚点，（b）给候选排序和展示
    score_by_name: dict[str, float | None] = {}
    try:
        results = await rag.entities_vdb.query(query_text, top_k=b.hit_top_k)
        for r in results or []:
            name = r.get("entity_name")
            if name is None:
                continue
            score_by_name[str(name)] = _safe_score(r.get("distance"))
    except Exception:
        return _degrade("vdb_error")

    anchors = q_names
    cited = [n for n in _literal_names(evidence_text, pool) if n not in anchors]
    anchor_mode = "literal"
    if not anchors:
        # 兜底锥点也只能从检索到的上下文里选：高亮集不得跑到上下文之外
        scored = [(n, s) for n, s in score_by_name.items() if s is not None and n in pool_set]
        if scored:
            anchors = [max(scored, key=lambda x: x[1])[0]]
            anchor_mode = "vector_fallback"
        else:
            anchor_mode = "none"

    if anchor_mode == "none" and not cited:
        # 问题问不到、答案引不到：没有可比对的锚点，不假装分层——把上下文原样交出去
        return _degrade("no_anchor")

    # 邻接表优先用全图（上下文子图可能缺中间边），拿不到图就退回上下文里的边
    rel_by_key: dict[frozenset, dict] = {}
    for r in full_relationships:
        s, t = str(r.get("src") or ""), str(r.get("tgt") or "")
        rel_by_key.setdefault(frozenset((s, t)), r)
    try:
        for e in await rag.chunk_entity_relation_graph.get_all_edges():
            s, t = str(e.get("source") or ""), str(e.get("target") or "")
            if not s or not t:
                continue
            rel_by_key.setdefault(
                frozenset((s, t)),
                {"src": s, "tgt": t, "description": e.get("description") or "",
                 "keywords": e.get("keywords") or "", "weight": e.get("weight")},
            )
    except Exception:
        pass
    adj = _undirected_adjacency([(str(r.get("src") or ""), str(r.get("tgt") or "")) for r in rel_by_key.values()])

    hit_layers = _layers_shell(anchor_mode, unmatched, budget=b)
    hit_layers["anchors"] = list(anchors)
    hit_layers["cited"] = list(cited)

    node_layer: dict[str, str] = {}
    for n in anchors:
        node_layer[n] = "anchor"
    for n in cited:
        node_layer.setdefault(n, "cited")
    used_edges: set[frozenset] = set()

    def _record(u: str, v: str, kind: str) -> None:
        paths = _shortest_paths(adj, u, v, max_hops=b.max_hops, max_paths=b.max_paths)
        if not paths:
            hit_layers["disconnected"].append({"a": u, "b": v, "kind": kind})
            return
        for p in paths:
            for mid in p[1:-1]:
                node_layer.setdefault(mid, "path")
            for x, y in zip(p, p[1:]):
                used_edges.add(frozenset((x, y)))
        hit_layers["paths"].append(
            {"from": u, "to": v, "kind": kind, "hops": len(paths[0]) - 1, "paths": paths}
        )

    for i, a in enumerate(anchors):
        for other in anchors[i + 1:]:
            _record(a, other, "anchor-anchor")
    for c in cited:
        cands = anchors or [t for t in node_layer if t != c]
        best: tuple[int, str] | None = None
        for a in cands:
            paths = _shortest_paths(adj, c, a, max_hops=b.max_hops, max_paths=b.max_paths)
            if paths and (best is None or len(paths[0]) < best[0]):
                best = (len(paths[0]) - 1, a)
        if best is None:
            hit_layers["disconnected"].append({"a": c, "b": anchors[0] if anchors else None, "kind": "cited-anchor"})
        else:
            _record(c, best[1], "cited-anchor")

    hit_names = set(node_layer)
    target_names = set(anchors) | set(cited)
    hit_relationships: list[dict] = []
    rel_seen: set[frozenset] = set()
    for r in full_relationships + list(rel_by_key.values()):
        s, t = str(r.get("src") or ""), str(r.get("tgt") or "")
        key = frozenset((s, t))
        if key in rel_seen or key not in used_edges:
            continue
        if s in hit_names and t in hit_names:
            rel_seen.add(key)
            # direct = 两端都是锚点/引用点（这条边本身就是证据）；path = 靠它中间才连上
            hit_relationships.append(
                {**r, "layer": "direct" if s in target_names and t in target_names else "path"}
            )

    by_name = {str(e.get("name")): e for e in full_entities}
    hit_entities = [
        {
            **by_name.get(n, {"name": n, "type": None, "description": None}),
            "name": n,
            "score": score_by_name.get(n),
            "layer": node_layer[n],
        }
        for n in sorted(hit_names, key=lambda x: (LAYER_ORDER.get(node_layer[x], 9), x))
    ]
    hit_layers["recall_only"] = [
        {"name": n, "score": score_by_name.get(n)} for n in pool if n not in hit_names
    ]

    trace["entities"] = hit_entities
    trace["relationships"] = hit_relationships
    trace["hit_layers"] = hit_layers
    return trace


def _layers_shell(
    mode: str, unmatched: list[str] | None = None, *, budget: RetrievalConfig | None = None
) -> dict:
    b = budget or RetrievalConfig()
    return {
        "anchor_mode": mode,
        "anchors": [],
        "cited": [],
        "paths": [],
        "disconnected": [],
        "recall_only": [],
        "unmatched_keywords": list(unmatched or []),
        "top_k": b.hit_top_k,
        "max_hops": b.max_hops,
        "max_paths": b.max_paths,
    }


async def query(
    rag,
    question: str,
    mode: str = "mix",
    hl_keywords: list[str] | None = None,
    ll_keywords: list[str] | None = None,
    budget: RetrievalConfig | None = None,
    *,
    anchor_text: str | None = None,
    evidence_text: str | None = None,
    generate_answer: bool = True,
) -> QueryResult:
    """跑一次检索，返回答案 + 结构化 trace。

    hl_keywords / ll_keywords 为空时由 LightRAG 走 LLM 关键词抽取；显式传入则跳过，
    用于确定性测试。

    双文本判据（M1）：`anchor_text` 管锚点、`evidence_text` 管证据，缺省分别回落到
    `question` 与答案文本（人问场景行为不变）。Agent 场景传
    `anchor_text=context.query · evidence_text=context.task`，证据位就不再依赖 LLM 答案的措辞。
    两者相等会抛 ValueError（见 `_hit_trace`：相等时证据层塌成空）。

    `generate_answer=False`（M2 的 Agent 面用）：不调 aquery，省掉一次答案生成的 LLM 调用——
    agent 自己会答，我们只给上下文。此模式下必须显式给 `evidence_text`，否则证据层无从产生，
    宁可报错也不返回一个看着正常、实则没有证据位的分层结果。
    """
    param = QueryParam(
        mode=mode,
        enable_rerank=False,
        hl_keywords=list(hl_keywords or []),
        ll_keywords=list(ll_keywords or []),
    )

    result = await rag.aquery_data(question, param)  # 真实错误（异常）直接上抛

    status = result.get("status")
    data = result.get("data") or {}
    metadata = result.get("metadata") or {}

    if status == "success":
        trace = _build_trace(data, metadata)
        if not (trace["entities"] or trace["relationships"]):
            # 上下文就是空的 → 不生成答案，绝不返回无据可查的黑盒
            return QueryResult(question=question, answer=NOT_FOUND_ANSWER, trace=trace, trace_hit=False)
        # 分层要用答案文本做判据，所以答案先出、路径后算（aquery 自带一次检索，与旧版同量）
        if generate_answer:
            answer = await rag.aquery(question, param)
        else:
            if evidence_text is None:
                raise ValueError(
                    "generate_answer=False 时必须显式给 evidence_text"
                    "（否则证据层没有来源，分层结果不可信）"
                )
            answer = ""  # Agent 面：不生成答案，只给上下文
        trace = await _hit_trace(
            rag,
            anchor_text if anchor_text is not None else question,
            evidence_text if evidence_text is not None else (answer or ""),
            trace,
            budget,
        )
    else:
        # 无结果（failure_reason == "no_results"）→ 如实报告未命中，不报错不编造
        trace = {
            "query_mode": mode,
            "keywords": {"high_level": list(hl_keywords or []), "low_level": list(ll_keywords or [])},
            "entities": [],
            "relationships": [],
            "chunks": [],
            "retrieved": {"entity_count": 0, "relation_count": 0, "entities": [], "relationships": []},
            "processing_info": {"failure_reason": metadata.get("failure_reason", "unknown")},
        }

    hit = bool(trace["entities"] or trace["relationships"])
    if not hit:
        return QueryResult(question=question, answer=NOT_FOUND_ANSWER, trace=trace, trace_hit=False)

    return QueryResult(question=question, answer=answer, trace=trace, trace_hit=True)
