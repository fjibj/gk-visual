"""检索问答：返回答案 + 结构化 trace（dual-level 命中：实体/关系/块 + 检索关键词）。

trace 即 S1 的"透明窗"数据源，S3 只负责渲染它，不再改检索逻辑。

硬约束（Failure Condition 1）：trace 为空时绝不返回黑盒答案——显式返回"未找到"，
不生成/不返回任何无据可查的答案。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lightrag import QueryParam

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
        "processing_info": metadata.get("processing_info"),
    }


def _safe_score(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


HIT_TOP_K = 5  # 核心实体截断：ll_keywords 检索实体的 top_k（再沿图扩散其邻居）


async def _hit_trace(rag, question: str, trace: dict) -> dict:
    """把 trace 的命中集合收敛为「核心实体 + 图扩散」的连通路径。

    背景：aquery_data 的 data["entities"] 是发给 LLM 的上下文子图（mix 模式 =
    local 实体检索 + global 关系主题检索 + chunk 关联），小图几乎=全图；且 global
    的关系向量检索会命中「话题相似但实体无关」的跨分量关系（问「字节跳动总部在哪」
    会命中「深圳→腾讯」，因两者都讲「总部位置」）。直接据此高亮会全图红/跨分量红。

    这里改按 LightRAG low-level（local）语义：用 ll_keywords（问题里的具体实体名，
    如「张三」「字节跳动」）检索实体向量库取 top_k 核心实体，再沿图扩散其 1 跳邻居
    边与端点。命中天然落在核心实体的连通分量内，独立分量与语义无关的全局关系被排除。
    向量库异常 → 诚实降级退回全图（score=None），绝不编造。
    """
    full_entities = trace.get("entities", [])
    full_relationships = trace.get("relationships", [])

    keywords = trace.get("keywords", {}) or {}
    ll_kw = [str(k) for k in (keywords.get("low_level") or [])]
    query_text = ", ".join(ll_kw) if ll_kw else question

    # 核心实体 + 分数（一次向量检索）
    core_names: list[str] = []
    score_by_name: dict[str, float | None] = {}
    try:
        results = await rag.entities_vdb.query(query_text, top_k=HIT_TOP_K)
        for r in results:
            name = r.get("entity_name")
            if name is None:
                continue
            core_names.append(str(name))
            score_by_name[str(name)] = _safe_score(r.get("distance"))
    except Exception:
        trace["entities"] = [{**e, "score": None} for e in full_entities]
        trace["relationships"] = [{**r, "score": None} for r in full_relationships]
        return trace

    core_set = set(core_names)

    # 图扩散：至少一端在核心实体内的边，及其端点（1 跳连通路径）
    hit_names = set(core_set)
    hit_relationships: list[dict] = []
    for r in full_relationships:
        s, t = str(r.get("src")), str(r.get("tgt"))
        if s in core_set or t in core_set:
            hit_relationships.append(r)
            hit_names.add(s)
            hit_names.add(t)

    # 组装实体：保留全图实体的 type/description，核心实体填 score
    hit_entities: list[dict] = []
    seen: set[str] = set()
    for e in full_entities:
        name = str(e.get("name"))
        if name in hit_names and name not in seen:
            seen.add(name)
            hit_entities.append({**e, "score": score_by_name.get(name)})
    for name in hit_names:
        if name not in seen:
            hit_entities.append(
                {"name": name, "type": None, "description": None, "score": score_by_name.get(name)}
            )

    trace["entities"] = hit_entities
    trace["relationships"] = hit_relationships
    return trace


async def query(
    rag,
    question: str,
    mode: str = "mix",
    hl_keywords: list[str] | None = None,
    ll_keywords: list[str] | None = None,
) -> QueryResult:
    """跑一次检索，返回答案 + 结构化 trace。

    hl_keywords / ll_keywords 为空时由 LightRAG 走 LLM 关键词抽取；显式传入则跳过，
    用于确定性测试。
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
        trace = await _hit_trace(rag, question, trace)
    else:
        # 无结果（failure_reason == "no_results"）→ 如实报告未命中，不报错不编造
        trace = {
            "query_mode": mode,
            "keywords": {"high_level": list(hl_keywords or []), "low_level": list(ll_keywords or [])},
            "entities": [],
            "relationships": [],
            "chunks": [],
            "processing_info": {"failure_reason": metadata.get("failure_reason", "unknown")},
        }

    hit = bool(trace["entities"] or trace["relationships"])
    if not hit:
        return QueryResult(question=question, answer=NOT_FOUND_ANSWER, trace=trace, trace_hit=False)

    answer = await rag.aquery(question, param)
    return QueryResult(question=question, answer=answer, trace=trace, trace_hit=True)
