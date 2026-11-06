"""溯源标签（M4 / backlog#9）：区分「从文档抽取的」与「人手工加的」，并把来源文档带出来。

## 为什么不另存一份账本

LightRAG 自己就留了痕，`origin` 是**读出来的**，不是记出来的：

| 来源 | `source_id` 长什么样 |
| --- | --- |
| 文档抽取 | 若干 chunk_id，用 `GRAPH_FIELD_SEP`（`<SEP>`）连起来 |
| 手工新建 | `"manual_creation"`（`utils_graph.acreate_entity` / `acreate_relation` 的默认值） |
| 两者都有 | 两样混在一个列表里（编辑过抽取实体、或合并把手工实体并进来之后） |

所以不需要旁挂存储，也就不会出现「账本和图各说一套」的漂移。代价是只能区分到
「有没有人碰过」，区分不出是哪个时代、哪个人碰的——那需要真正的审计日志，不在本阶段。

## 为什么 chunk→文档 要走块存储

节点自己也有 `file_path` 字段，但老数据里是 `unknown_source`（早期 CLI 摄入没给 file_path）。
而 `rag.text_chunks` 的每条记录都有真的 `full_doc_id` 和 `file_path`，所以来源文档一律从
块存储反查，节点字段只当兜底。这跟 `documents._doc_entity_relation_counts` 用的是同一套依据。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

try:  # 与 LightRAG 的列表分隔符保持一致；拿不到就按约定值兜底
    from lightrag.utils import GRAPH_FIELD_SEP
except Exception:  # noqa: BLE001
    GRAPH_FIELD_SEP = "<SEP>"

logger = logging.getLogger(__name__)

# origin 的四种取值。别人（前端 / agent）会照着这个集合写判断，改动要当契约对待。
ORIGIN_EXTRACTED = "extracted"  # 全部来自文档抽取
ORIGIN_MANUAL = "manual"  # 全部来自人工创建
ORIGIN_MIXED = "mixed"  # 文档抽取 + 人工改动（编辑/合并之后就会变成这样）
ORIGIN_UNKNOWN = "unknown"  # 没有任何来源记录（老数据 / 来源被清空）

MANUAL_SENTINEL = "manual_creation"
"""LightRAG 在手工新建时写进 source_id / file_path 的哨兵值。"""

# 这些值不是「某块内容」，不能被当成 chunk_id 去反查。
NON_CHUNK_REFS = frozenset({MANUAL_SENTINEL, "unknown_source", "unknown", ""})


def split_refs(value) -> list[str]:
    """把 `source_id` / `file_path` 拆成去空后的列表（也接受已经是列表的入参）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = [str(v) for v in value]
    else:
        raw = str(value).split(GRAPH_FIELD_SEP)
    return [p.strip() for p in raw if p and p.strip()]


def origin_of(source_id) -> str:
    """由 `source_id` 判定 origin。规则只有三条，靠结构不靠阈值。"""
    refs = split_refs(source_id)
    if not refs:
        return ORIGIN_UNKNOWN
    manual = MANUAL_SENTINEL in refs
    extracted = any(r not in NON_CHUNK_REFS for r in refs)
    if manual and extracted:
        return ORIGIN_MIXED
    if manual:
        return ORIGIN_MANUAL
    return ORIGIN_EXTRACTED


@dataclass
class Provenance:
    """一条实体/关系的来源说明。

    `docs` 是给人看的名字（文档标题），`doc_ids` 是给程序用的身份。
    `unresolved` 是「source_id 说有这块、块存储里却找不到」的条数——文档被覆盖/删除后
    就会出现，如实计数而不是当作没发生（那正是「这部分内容已经无据可查」）。
    """

    origin: str = ORIGIN_UNKNOWN
    manual: bool = False
    docs: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    chunks: int = 0
    unresolved: int = 0

    def as_dict(self) -> dict:
        return {
            "manual": self.manual,
            "docs": list(self.docs),
            "doc_ids": list(self.doc_ids),
            "chunks": self.chunks,
            "unresolved": self.unresolved,
        }


async def _chunk_docs(rag, chunk_ids: Iterable[str]) -> dict[str, tuple[str, str]]:
    """chunk_id → (doc_id, 显示名)。一次批量取；取不到的（块已删）不出现在结果里。"""
    ids = [c for c in dict.fromkeys(chunk_ids) if c]
    if not ids:
        return {}
    try:
        rows = await rag.text_chunks.get_by_ids(ids)
    except Exception as exc:  # noqa: BLE001 — 溯源查不到不该让读图整个失败
        logger.warning("溯源：块存储批量查询失败，来源文档将为空（%s: %s）", type(exc).__name__, exc)
        return {}

    out: dict[str, tuple[str, str]] = {}
    for cid, row in zip(ids, rows):
        if not row:
            continue
        doc_id = str(row.get("full_doc_id") or "")
        file_path = str(row.get("file_path") or "")
        title = file_path if file_path not in NON_CHUNK_REFS else (doc_id or file_path)
        out[cid] = (doc_id, title)
    return out


async def annotate(rag, records: list[dict]) -> list[Provenance]:
    """给一批原始图记录（节点或边，需带 `source_id`）算 provenance，顺序与入参一致。"""
    refs_per = [split_refs(r.get("source_id")) for r in records]
    wanted: list[str] = []
    for refs in refs_per:
        wanted.extend(r for r in refs if r not in NON_CHUNK_REFS)
    index = await _chunk_docs(rag, wanted)

    out: list[Provenance] = []
    for refs in refs_per:
        chunk_refs = [r for r in refs if r not in NON_CHUNK_REFS]
        docs: list[str] = []
        doc_ids: list[str] = []
        unresolved = 0
        for cid in chunk_refs:
            hit = index.get(cid)
            if not hit:
                unresolved += 1
                continue
            doc_id, title = hit
            if title and title not in docs:
                docs.append(title)
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)
        out.append(
            Provenance(
                origin=origin_of(refs),
                manual=MANUAL_SENTINEL in refs,
                docs=docs,
                doc_ids=doc_ids,
                chunks=len(chunk_refs),
                unresolved=unresolved,
            )
        )
    return out


# ---------------------------------------------------------------- 按名字取（MCP 用）


async def for_entities(rag, names: Iterable[str]) -> dict[str, Provenance]:
    """实体名 → Provenance。取不到的实体不出现在结果里（调用方按 `unknown` 兜底）。"""
    pairs: list[tuple[str, dict]] = []
    for name in dict.fromkeys(n for n in names if n):
        try:
            node = await rag.chunk_entity_relation_graph.get_node(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("溯源：读实体 %s 失败（%s: %s）", name, type(exc).__name__, exc)
            continue
        if node:
            pairs.append((name, node))
    provs = await annotate(rag, [data for _, data in pairs])
    return {name: p for (name, _), p in zip(pairs, provs)}


async def for_relations(rag, pairs: Iterable[tuple[str, str]]) -> dict[str, Provenance]:
    """`"源->目标"` → Provenance（键与 `memory_api.relation_ref` 的取值一致）。"""
    found: list[tuple[str, dict]] = []
    for src, tgt in dict.fromkeys((s, t) for s, t in pairs if s and t):
        try:
            edge = await rag.chunk_entity_relation_graph.get_edge(src, tgt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("溯源：读关系 %s->%s 失败（%s: %s）", src, tgt, type(exc).__name__, exc)
            continue
        if edge:
            found.append((f"{src}->{tgt}", edge))
    provs = await annotate(rag, [data for _, data in found])
    return {key: p for (key, _), p in zip(found, provs)}
