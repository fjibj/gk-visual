"""编辑回路数据层测试：编辑 API 调用后图状态正确变化（离线 mock embedding）。

语义检索回路（编辑→检索命中/分数变化）由 holdout 用真实 bge-m3 判卷；
此处锁定「编辑→图」的数据层基础（mock 哈希向量做不了语义匹配）。
"""

from __future__ import annotations

import asyncio

from graphkb.rag import init_rag

KG = {
    "chunks": [{"content": "张三在字节跳动工作，字节跳动总部位于北京。", "source_id": "chunk-1"}],
    "entities": [
        {"entity_name": "张三", "entity_type": "person", "description": "软件工程师", "source_id": "chunk-1"},
        {"entity_name": "字节跳动", "entity_type": "organization", "description": "科技公司", "source_id": "chunk-1"},
        {"entity_name": "北京", "entity_type": "location", "description": "城市", "source_id": "chunk-1"},
    ],
    "relationships": [
        {"src_id": "张三", "tgt_id": "字节跳动", "description": "工作于", "keywords": "任职", "weight": 1.0, "source_id": "chunk-1"},
        {"src_id": "字节跳动", "tgt_id": "北京", "description": "总部位于", "keywords": "位于", "weight": 1.0, "source_id": "chunk-1"},
    ],
}


def _names(nodes):
    return {n.get("entity_id") for n in nodes}


def test_edit_entity_updates_graph(mock_config):
    async def run():
        rag = await init_rag(mock_config)
        await rag.ainsert_custom_kg(KG)
        await rag.aedit_entity("张三", {"description": "数据科学家"})
        node = await rag.chunk_entity_relation_graph.get_node("张三")
        await rag.finalize_storages()
        return node.get("description")

    assert asyncio.run(run()) == "数据科学家"


def test_delete_entity_removes_node_and_relations(mock_config):
    async def run():
        rag = await init_rag(mock_config)
        await rag.ainsert_custom_kg(KG)
        await rag.adelete_by_entity("北京")
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        await rag.finalize_storages()
        return _names(nodes), len(edges)

    names, n_edges = asyncio.run(run())
    assert "北京" not in names
    assert n_edges == 1  # 只剩 张三->字节跳动


def test_merge_removes_source_and_retargets_relation(mock_config):
    async def run():
        rag = await init_rag(mock_config)
        await rag.ainsert_custom_kg(KG)
        await rag.amerge_entities(source_entities=["张三"], target_entity="李四")
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        await rag.finalize_storages()
        return _names(nodes), {(e.get("source"), e.get("target")) for e in edges}

    names, edges = asyncio.run(run())
    assert "张三" not in names and "李四" in names
    assert ("李四", "字节跳动") in edges or ("字节跳动", "李四") in edges


def test_create_entity_and_relation_adds_to_graph(mock_config):
    async def run():
        rag = await init_rag(mock_config)
        await rag.ainsert_custom_kg(KG)
        await rag.acreate_entity("上海", {"entity_type": "location", "description": "中国直辖市"})
        await rag.acreate_relation("字节跳动", "上海", {"description": "总部位于上海", "keywords": "总部"})
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        await rag.finalize_storages()
        return _names(nodes), {(e.get("source"), e.get("target")) for e in edges}

    names, edges = asyncio.run(run())
    assert "上海" in names
    assert ("字节跳动", "上海") in edges or ("上海", "字节跳动") in edges
