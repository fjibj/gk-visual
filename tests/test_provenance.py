"""M4 溯源标签：origin 四态判定 + chunk→文档 解析（全离线，不联网）。"""

from __future__ import annotations

import asyncio

from graphkb.provenance import (
    ORIGIN_EXTRACTED,
    ORIGIN_MANUAL,
    ORIGIN_MIXED,
    ORIGIN_UNKNOWN,
    annotate,
    for_entities,
    for_relations,
    origin_of,
    split_refs,
)

# ---------------------------------------------------------------- 假对象


class _Chunks:
    def __init__(self, rows: dict | None = None, boom: bool = False):
        self.rows = rows or {}
        self.boom = boom

    async def get_by_ids(self, ids):
        if self.boom:
            raise RuntimeError("块存储炸了")
        return [self.rows.get(str(i)) for i in ids]


class _Graph:
    def __init__(self, nodes: dict | None = None, edges: dict | None = None):
        self.nodes = nodes or {}
        self.edges = edges or {}

    async def get_node(self, name):
        return self.nodes.get(str(name))

    async def get_edge(self, src, tgt):
        return self.edges.get((str(src), str(tgt)))


class _Rag:
    def __init__(self, chunks: _Chunks, graph: _Graph | None = None):
        self.text_chunks = chunks
        self.chunk_entity_relation_graph = graph or _Graph()


def _rag(rows: dict | None = None, boom: bool = False, graph: _Graph | None = None) -> _Rag:
    return _Rag(_Chunks(rows, boom=boom), graph)


DOC_ROWS = {
    "c1": {"full_doc_id": "张三简历", "file_path": "张三简历"},
    "c2": {"full_doc_id": "项目周报", "file_path": "项目周报"},
}


# ---------------------------------------------------------------- origin 判定


def test_split_refs_handles_sep_and_lists():
    assert split_refs("a<SEP>b") == ["a", "b"]
    assert split_refs(["a", " b "]) == ["a", "b"]
    assert split_refs("") == []
    assert split_refs(None) == []


def test_origin_four_states():
    """四种取值全靠结构判定，没有阈值、没有猜测。"""
    assert origin_of("doc-1-chunk-000") == ORIGIN_EXTRACTED
    assert origin_of("manual_creation") == ORIGIN_MANUAL
    assert origin_of("doc-1-chunk-000<SEP>manual_creation") == ORIGIN_MIXED
    assert origin_of("") == ORIGIN_UNKNOWN
    assert origin_of(None) == ORIGIN_UNKNOWN
    assert origin_of([]) == ORIGIN_UNKNOWN
    # 列表形态也认（LightRAG 有些路径给的是 list）
    assert origin_of(["manual_creation"]) == ORIGIN_MANUAL


def test_annotate_resolves_docs_and_counts_chunks():
    prov = asyncio.run(
        annotate(_rag(DOC_ROWS), [{"source_id": "c1<SEP>c2<SEP>manual_creation"}])
    )[0]
    assert prov.origin == ORIGIN_MIXED
    assert prov.manual is True
    assert prov.docs == ["张三简历", "项目周报"]
    assert prov.doc_ids == ["张三简历", "项目周报"]
    assert prov.chunks == 2
    assert prov.unresolved == 0


def test_annotate_orders_input_unchanged():
    provs = asyncio.run(
        annotate(_rag(DOC_ROWS), [{"source_id": "c2"}, {"source_id": "c1"}])
    )
    assert [p.docs for p in provs] == [["项目周报"], ["张三简历"]]


def test_annotate_reports_unresolved_instead_of_hiding_it():
    """文档被覆盖/删除后块会消失：如实计数（内容已无据可查），而不是当作「没这回事」。"""
    prov = asyncio.run(annotate(_rag(DOC_ROWS), [{"source_id": "c1<SEP>c-gone"}]))[0]
    assert prov.origin == ORIGIN_EXTRACTED
    assert prov.docs == ["张三简历"]
    assert prov.chunks == 2
    assert prov.unresolved == 1


def test_annotate_survives_chunk_storage_failure():
    """块存储读挂了不该让整个读图崩：来源留空，unresolved 记满，origin 仍是读出来的。"""
    prov = asyncio.run(annotate(_rag(DOC_ROWS, boom=True), [{"source_id": "c1"}]))[0]
    assert prov.origin == ORIGIN_EXTRACTED
    assert prov.docs == []
    assert prov.unresolved == 1


def test_file_path_sentinel_falls_back_to_doc_id():
    """老数据的 chunk.file_path 是 unknown_source，退回 doc_id，不要把这串哨兵当文档名。"""
    rows = {"c1": {"full_doc_id": "doc-7286", "file_path": "unknown_source"}}
    prov = asyncio.run(annotate(_rag(rows), [{"source_id": "c1"}]))[0]
    assert prov.docs == ["doc-7286"]


def test_annotate_without_source_id_is_unknown():
    prov = asyncio.run(annotate(_rag(DOC_ROWS), [{"description": "手工时代留下的节点"}]))[0]
    assert prov.origin == ORIGIN_UNKNOWN
    assert prov.manual is False
    assert prov.chunks == 0


# ---------------------------------------------------------------- 按名字取（MCP 用）


def test_for_entities_keys_by_name_and_skips_missing():
    graph = _Graph(
        nodes={
            "张三": {"entity_type": "person", "source_id": "c1"},
            "手工点": {"entity_type": "concept", "source_id": "manual_creation"},
        }
    )
    got = asyncio.run(for_entities(_rag(DOC_ROWS, graph=graph), ["张三", "手工点", "不存在"]))
    assert got["张三"].origin == ORIGIN_EXTRACTED
    assert got["张三"].docs == ["张三简历"]
    assert got["手工点"].origin == ORIGIN_MANUAL
    assert "不存在" not in got, "取不到的实体不进结果，由调用方按 unknown 兜底"


def test_for_relations_keys_use_arrow_shape():
    graph = _Graph(edges={("张三", "字节跳动"): {"source_id": "c1"}})
    got = asyncio.run(for_relations(_rag(DOC_ROWS, graph=graph), [("张三", "字节跳动")]))
    assert list(got) == ["张三->字节跳动"]
    assert got["张三->字节跳动"].origin == ORIGIN_EXTRACTED
