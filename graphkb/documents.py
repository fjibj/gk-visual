"""文档生命周期：上传（含覆盖更新）、列表、删除。

复用 LightRAG ``ainsert`` / ``adelete_by_doc_id``（其内置「部分受影响实体用剩余文档缓存重建」）。
文档身份 = 标题规范化（slug），同标题 = 同文档；覆盖更新 = 先删旧再插新。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lightrag.base import DocStatus
from lightrag.utils import GRAPH_FIELD_SEP


def slugify(title: str) -> str:
    """标题 → 稳定 doc_id：保中文/字母/数字，其余转 '-'。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(title).strip()).strip("-")
    return s or "untitled"


@dataclass
class DocumentInfo:
    doc_id: str = ""
    title: str = ""
    content_length: int = 0
    entity_count: int = 0
    relation_count: int = 0


@dataclass
class UpsertResult:
    doc_id: str = ""
    created: bool = False  # True=新建，False=覆盖更新
    entity_count: int = 0
    relation_count: int = 0


async def _doc_entity_relation_counts(rag, chunks_list: list[str]) -> tuple[int, int]:
    """按文档 chunks_list 统计贡献的实体数/关系数（source_id 与 chunk 求交）。"""
    chunks = set(chunks_list or [])
    nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
    edges = await rag.chunk_entity_relation_graph.get_all_edges()

    e = 0
    for n in nodes:
        srcs = {p for p in str(n.get("source_id") or "").split(GRAPH_FIELD_SEP) if p}
        if srcs & chunks:
            e += 1
    r = 0
    for edge in edges:
        srcs = {p for p in str(edge.get("source_id") or "").split(GRAPH_FIELD_SEP) if p}
        if srcs & chunks:
            r += 1
    return e, r


async def _processed_docs(rag) -> dict:
    """已处理文档表 {doc_id: DocProcessingStatus}。

    LightRAG 1.5.7 删掉了 facade 方法 `rag.get_docs_by_status(status)`（升上去直接
    AttributeError——CI 在 1.5.7 上就是这么红的）；能力搬到了底层
    `doc_status.get_docs_by_statuses(statuses, strict=False)`，而 1.5.6 也早就有这个。
    走底层 = 两个版本都能跑，不必把 lightrag 钉死在旧版。
    """
    return await rag.doc_status.get_docs_by_statuses([DocStatus.PROCESSED])


async def list_documents(rag) -> list[DocumentInfo]:
    """列出已处理文档（含各自贡献的实体/关系数）。"""
    docs = await _processed_docs(rag)
    result = []
    for doc_id, st in docs.items():
        e, r = await _doc_entity_relation_counts(rag, st.chunks_list or [])
        result.append(
            DocumentInfo(
                doc_id=doc_id,
                title=st.file_path or doc_id,
                content_length=st.content_length or 0,
                entity_count=e,
                relation_count=r,
            )
        )
    result.sort(key=lambda d: d.doc_id)
    return result


async def upsert_document(rag, title: str, content: str) -> UpsertResult:
    """上传 / 覆盖更新文档：同 doc_id 已存在则先删旧再插新。

    spike 证实：同 doc_id 直接重插会被 LightRAG duplicate 检测拦截，必须「先删后插」。
    """
    if not str(content).strip():
        raise ValueError("文档内容不能为空")
    doc_id = slugify(title)
    docs = await _processed_docs(rag)
    existed = doc_id in docs
    if existed:
        await rag.adelete_by_doc_id(doc_id)

    await rag.ainsert(content, ids=[doc_id], file_paths=[str(title).strip() or doc_id])

    docs = await _processed_docs(rag)
    st = docs.get(doc_id)
    e, r = await _doc_entity_relation_counts(rag, st.chunks_list if st else [])
    return UpsertResult(
        doc_id=doc_id,
        created=not existed,
        entity_count=e,
        relation_count=r,
    )


async def delete_document(rag, doc_id: str) -> dict:
    """删除文档（LightRAG 收敛：独有实体/关系清理，共享实体用剩余文档重建）。"""
    return await rag.adelete_by_doc_id(doc_id)
