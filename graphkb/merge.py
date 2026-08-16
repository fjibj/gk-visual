"""显式实体合并：复用 LightRAG amerge_entities，返回结构化对齐结果。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MergeResult:
    target_entity: str = ""
    deleted_entities: list[str] = field(default_factory=list)
    relationships_transferred: int = 0
    target_final: dict = field(default_factory=dict)


async def _relations_of(rag, entity: str) -> set[tuple[str, str]]:
    """返回图中以 entity 为源或目标的关系集合（规范化 source/target）。"""
    edges = await rag.chunk_entity_relation_graph.get_all_edges()
    rels: set[tuple[str, str]] = set()
    for e in edges:
        s = str(e.get("source", ""))
        t = str(e.get("target", ""))
        if s == entity or t == entity:
            rels.add((s, t))
    return rels


async def merge_entities(
    rag, source_entities: list[str], target_entity: str
) -> MergeResult:
    """把多个源实体合并到目标实体，复用 LightRAG ``amerge_entities``。

    返回结构化结果：删除的源、转移到目标的关系数、目标终态。
    """
    before_target = await _relations_of(rag, target_entity)

    result = await rag.amerge_entities(
        source_entities=list(source_entities),
        target_entity=target_entity,
    )

    after_target = await _relations_of(rag, target_entity)
    transferred = len(after_target - before_target)

    return MergeResult(
        target_entity=str(result.get("entity_name") or target_entity),
        deleted_entities=list(source_entities),
        relationships_transferred=transferred,
        target_final=dict(result.get("graph_data") or {}),
    )
