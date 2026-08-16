"""documents.py 单元测试：slugify + 覆盖更新逻辑 + 贡献计数（_FakeRag 锁定）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from graphkb.documents import _doc_entity_relation_counts, slugify, upsert_document


def test_slugify():
    assert slugify("我的笔记") == "我的笔记"
    assert slugify("My Note 123") == "My-Note-123"
    assert slugify("  ") == "untitled"
    assert slugify("a/b\\c") == "a-b-c"


class _FakeGraph:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

    async def get_all_nodes(self):
        return self.nodes

    async def get_all_edges(self):
        return self.edges


class _FakeRag:
    def __init__(self, nodes, edges):
        self.docs: dict = {}
        self.calls: list = []
        self.chunk_entity_relation_graph = _FakeGraph(nodes, edges)

    async def get_docs_by_status(self, status):
        return self.docs

    async def ainsert(self, text, ids=None, file_paths=None):
        self.calls.append(("insert", ids))
        self.docs[ids[0]] = SimpleNamespace(
            file_path=file_paths[0],
            content_length=len(text),
            chunks_list=[f"{ids[0]}-chunk-000"],
        )

    async def adelete_by_doc_id(self, doc_id):
        self.calls.append(("delete", doc_id))
        self.docs.pop(doc_id, None)
        return SimpleNamespace(status="success", message="ok")


NODES = [
    {"entity_id": "张三", "source_id": "doc-a-chunk-000"},
    {"entity_id": "北京", "source_id": "doc-a-chunk-000<SEP>doc-b-chunk-000"},
    {"entity_id": "李四", "source_id": "doc-b-chunk-000"},
]
EDGES = [
    {"source": "张三", "target": "北京", "source_id": "doc-a-chunk-000"},
    {"source": "李四", "target": "北京", "source_id": "doc-b-chunk-000"},
]


def test_upsert_creates_new_document():
    rag = _FakeRag(NODES, EDGES)
    result = asyncio.run(upsert_document(rag, "笔记A", "内容"))
    assert result.created is True
    assert result.doc_id == "笔记A"
    assert rag.calls == [("insert", ["笔记A"])]


def test_upsert_overwrites_existing_document():
    rag = _FakeRag(NODES, EDGES)
    rag.docs["笔记A"] = SimpleNamespace(file_path="笔记A", content_length=3, chunks_list=["笔记A-chunk-000"])
    result = asyncio.run(upsert_document(rag, "笔记A", "新内容"))
    assert result.created is False
    assert rag.calls == [("delete", "笔记A"), ("insert", ["笔记A"])]


def test_doc_entity_relation_counts():
    rag = _FakeRag(NODES, EDGES)
    # 文档 A 的 chunk 是 doc-a-chunk-000：贡献 张三、北京（2 实体）+ 张三->北京（1 关系）
    e, r = asyncio.run(_doc_entity_relation_counts(rag, ["doc-a-chunk-000"]))
    assert e == 2
    assert r == 1
