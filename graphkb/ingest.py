"""文档摄入：单篇文本 → LightRAG 图，返回实体/关系计数。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IngestResult:
    doc_id: str = ""
    entity_count: int = 0
    relation_count: int = 0
    entities: list[str] = field(default_factory=list)
    relations: list[tuple[str, str]] = field(default_factory=list)


async def ingest_document(rag, text: str, doc_id: str | None = None) -> IngestResult:
    """把单篇文本摄入 LightRAG，返回构图结果（含实体/关系计数）。

    doc_id 参数暂未使用（LightRAG 的 ainsert 对单篇文本自动分块；跨文档去重交给 S2）。
    """
    result_id = await rag.ainsert(text)

    graph = rag.chunk_entity_relation_graph
    nodes = await graph.get_all_nodes()
    edges = await graph.get_all_edges()

    entities = [str(n.get("entity_id") or n.get("id") or n) for n in nodes]
    relations = [(str(e.get("source", "")), str(e.get("target", ""))) for e in edges]

    return IngestResult(
        doc_id=str(result_id),
        entity_count=len(nodes),
        relation_count=len(edges),
        entities=entities,
        relations=relations,
    )
