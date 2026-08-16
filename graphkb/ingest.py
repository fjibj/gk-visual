"""文档摄入：单篇文本 → LightRAG 图，返回实体/关系计数 + 本次新增实体。"""

from __future__ import annotations

from dataclasses import dataclass, field


def _entity_name(node) -> str:
    return str(node.get("entity_id") or node.get("id") or node)


@dataclass
class IngestResult:
    doc_id: str = ""
    entity_count: int = 0
    relation_count: int = 0
    entities: list[str] = field(default_factory=list)
    relations: list[tuple[str, str]] = field(default_factory=list)
    new_entities: list[str] = field(default_factory=list)
    lost_entities: list[str] = field(default_factory=list)


async def ingest_document(rag, text: str) -> IngestResult:
    """把单篇文本增量摄入 LightRAG，返回构图结果。

    - 增量：多次调用累积、不重建整库（LightRAG ainsert 现成能力）。
    - 对齐：同名实体跨文档由 LightRAG 自动合并为单节点；变体实体靠
      ``merge_entities``（graphkb/merge.py）显式合并。
    - ``new_entities``：本次摄入新增的实体名（与摄入前差集），让"增量并入"可见。
    - ``lost_entities``：摄入前有、摄入后消失的实体名（正常应为空）；非空即
      增量丢失（图被重建/实体被吞），显式暴露，绝不静默。
    """
    graph = rag.chunk_entity_relation_graph
    before = {_entity_name(n) for n in await graph.get_all_nodes()}

    result_id = await rag.ainsert(text)

    nodes = await graph.get_all_nodes()
    edges = await graph.get_all_edges()

    entities = [_entity_name(n) for n in nodes]
    relations = [(str(e.get("source", "")), str(e.get("target", ""))) for e in edges]
    after = set(entities)
    new_entities = sorted(after - before)
    lost_entities = sorted(before - after)

    return IngestResult(
        doc_id=str(result_id),
        entity_count=len(nodes),
        relation_count=len(edges),
        entities=entities,
        relations=relations,
        new_entities=new_entities,
        lost_entities=lost_entities,
    )
