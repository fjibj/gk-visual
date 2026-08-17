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


HIT_TOP_K = 5  # 可视化"命中"截断：只高亮向量检索最相关的 top_k 实体/关系


async def _hit_trace(rag, question: str, trace: dict) -> dict:
    """把 trace 的命中集合从「LightRAG 上下文子图」收敛为「向量检索 top_k」。

    背景：aquery_data 的 data["entities"] 是发给 LLM 的上下文子图，包含命中实体
    + 邻居扩散 + low-level chunk 关联，小图几乎=全图，直接据此高亮会「全图红色」。
    这里复用与 LightRAG high-level 同源的 entities_vdb / relationships_vdb 向量检索
    取 top_k，只保留真正命中的实体/关系，并从全图 trace 补回 type/description/
    keywords/weight，同时填 score。查询异常/查不到 → 诚实降级（保留原集合，
    score 为 None），绝不编造。
    """
    full_entities = trace.get("entities", [])
    full_relationships = trace.get("relationships", [])
    ent_by_name = {str(e.get("name")): e for e in full_entities if e.get("name")}
    rel_by_key = {}
    for r in full_relationships:
        s, t = r.get("src"), r.get("tgt")
        if s and t:
            rel_by_key[tuple(sorted((str(s), str(t))))] = r

    hit_entities = []
    try:
        results = await rag.entities_vdb.query(question, top_k=HIT_TOP_K)
        for r in results:
            name = r.get("entity_name")
            if name is None:
                continue
            base = ent_by_name.get(str(name), {})
            hit_entities.append(
                {
                    "name": name,
                    "type": base.get("type") or r.get("entity_type"),
                    "description": base.get("description") or r.get("description"),
                    "score": _safe_score(r.get("distance")),
                }
            )
    except Exception:
        hit_entities = [{**e, "score": None} for e in full_entities]

    hit_relationships = []
    try:
        results = await rag.relationships_vdb.query(question, top_k=HIT_TOP_K)
        for r in results:
            s, t = r.get("src_id"), r.get("tgt_id")
            if s is None or t is None:
                continue
            key = tuple(sorted((str(s), str(t))))
            base = rel_by_key.get(key, {})
            hit_relationships.append(
                {
                    "src": s,
                    "tgt": t,
                    "description": base.get("description") or r.get("description"),
                    "keywords": base.get("keywords") or r.get("keywords"),
                    "weight": (
                        base.get("weight")
                        if base.get("weight") is not None
                        else r.get("weight")
                    ),
                    "score": _safe_score(r.get("distance")),
                }
            )
    except Exception:
        hit_relationships = [{**r, "score": None} for r in full_relationships]

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
