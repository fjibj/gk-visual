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
