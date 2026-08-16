"""检索问答：返回答案 + 结构化 trace（dual-level 命中：实体/关系/块 + 检索关键词）。

trace 即 S1 的"透明窗"数据源，S3 只负责渲染它，不再改检索逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lightrag import QueryParam


@dataclass
class QueryResult:
    question: str = ""
    answer: str = ""
    trace: dict = field(default_factory=dict)


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


async def query(rag, question: str, mode: str = "mix") -> QueryResult:
    """跑一次检索，返回答案 + 结构化 trace。

    注意：answer 与 trace 是两次调用（aquery / aquery_data），关键词抽取有 LLM 缓存、
    向量检索走本地 bge-m3，成本可忽略；后续切片可合并为单次。
    """
    param = QueryParam(mode=mode, enable_rerank=False)
    answer = await rag.aquery(question, param)
    result = await rag.aquery_data(question, param)

    trace = _build_trace(result.get("data", {}), result.get("metadata", {}))
    return QueryResult(question=question, answer=answer, trace=trace)
