"""rag.py 的同进程隔离：两个实例同 workspace、不同库目录，必须各读各的。

背景：LightRAG 的 KV 数据挂在进程级共享字典上，「谁负责从磁盘加载」只是全局初始化标志。
第二个实例会看到「已初始化」而跳过读文件 → `text_chunks` 空。真图回归就是这么红的
（单独跑一个文件全绿，跑整套却报「块存储里没有这个 chunk」）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from graphkb.config import Config, EmbeddingConfig, LLMConfig
from graphkb.rag import _clear_shared_namespaces, init_rag, reset_rag


def _cfg(working_dir: Path, workspace: str = "") -> Config:
    return Config(
        llm=LLMConfig(provider="mock"),
        embedding=EmbeddingConfig(provider="mock", dim=8),
        working_dir=str(working_dir),
        workspace=workspace,
    )


def _write_chunks(path: Path, rows: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "kv_store_text_chunks.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )


def _chunk(cid: str, text: str) -> dict:
    return {
        "tokens": len(text),
        "content": text,
        "chunk_order_index": 0,
        "full_doc_id": f"doc-{cid}",
        "file_path": f"{cid}.md",
    }


def test_single_instance_reads_its_own_chunks(tmp_path):
    """基线：只有一个实例时，块照常读得到（不需要任何隔离）。"""
    ws = tmp_path / "solo"
    _write_chunks(ws, {"solo-1": _chunk("solo-1", "只有我这一块")})

    async def run():
        rag = await init_rag(_cfg(ws))
        try:
            return await rag.text_chunks.get_by_ids(["solo-1", "别人的-1"])
        finally:
            await rag.finalize_storages()

    got = asyncio.run(run())
    assert got[0] and got[0]["content"] == "只有我这一块"
    assert got[1] is None


def test_two_instances_same_workspace_are_isolated(tmp_path):
    """同 workspace、不同库目录：各读各的块，互不串（这就是真图回归里挂掉的那条）。"""
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    _write_chunks(ws_a, {"a-1": _chunk("a-1", "A 的块")})
    _write_chunks(ws_b, {"b-1": _chunk("b-1", "B 的块")})

    async def run():
        rag_a = await init_rag(_cfg(ws_a))
        rag_b = await init_rag(_cfg(ws_b))
        try:
            return (
                await rag_a.text_chunks.get_by_ids(["a-1", "b-1"]),
                await rag_b.text_chunks.get_by_ids(["a-1", "b-1"]),
            )
        finally:
            await rag_a.finalize_storages()
            await rag_b.finalize_storages()

    got_a, got_b = asyncio.run(run())
    assert got_a[0] and got_a[0]["content"] == "A 的块"
    assert got_a[1] is None, "A 不许看见 B 的块"
    assert got_b[1] and got_b[1]["content"] == "B 的块"
    assert got_b[0] is None, "B 不许看见 A 的块"


def test_same_dir_twice_keeps_upstream_sharing(tmp_path):
    """同一个库重复建实例不算冲突：两边看到的都是这一库的内容，不会因为“脱钩”而丢数据。

    （内存对象是否同一个取决于进程里先前有没有人初始化过这个 namespace，
    那是全局标志，不归本用例断言——这里只钉住“数据看得到且不串”。）
    """
    ws = tmp_path / "same"
    _write_chunks(ws, {"same-1": _chunk("same-1", "同一个库")})

    async def run():
        rag1 = await init_rag(_cfg(ws))
        rag2 = await init_rag(_cfg(ws))
        try:
            a = await rag1.text_chunks.get_by_ids(["same-1"])
            b = await rag2.text_chunks.get_by_ids(["same-1"])
            return a, b
        finally:
            await rag1.finalize_storages()
            await rag2.finalize_storages()

    a, b = asyncio.run(run())
    assert a[0] and a[0]["content"] == "同一个库"
    assert b[0] and b[0]["content"] == "同一个库"


# ---------------------------------------------------------------- reset（判卷机用）


def test_clear_shared_namespaces_also_drops_the_reference_cache(tmp_path):
    """清共享命名空间时必须连对象缓存一起清，否则重置看起来成功、实际什么都没清。

    这是 2026-11-21 接 idsd-harness 时蹲到的：LightRAG 1.5.7 加了
    `_namespace_data_cache`（免得每次拿锁），只删 `_shared_dicts` 的话，新实例会从
    缓存里拿回**同一个旧字典对象**——图清空了（图不走共享字典），文档和块却还在。
    """
    from lightrag.kg import shared_storage

    if not isinstance(getattr(shared_storage, "_namespace_data_cache", None), dict):
        return  # 上游换实现就别硬试，测试保持“能跳就跳”

    async def run():
        ws = tmp_path / "cache"
        _write_chunks(ws, {"c-1": _chunk("c-1", "缓存里的块")})
        rag = await init_rag(_cfg(ws))
        try:
            first = await rag.text_chunks.get_by_ids(["c-1"])
            assert first[0] is not None
            cleared = _clear_shared_namespaces("")
            return cleared, [c for c in cleared if c.startswith("_namespace_data_cache:")]
        finally:
            await rag.finalize_storages()

    cleared, cache_cleared = asyncio.run(run())
    assert cleared, "什么都没清：键名前缀判断有问题"
    assert cache_cleared, "没清对象缓存：重置后会读回同一个旧字典"


def test_reset_rag_gives_an_empty_store(tmp_path):
    """重置后必须是真空库：文档、块、图一起没（不是只少了图）。"""

    async def run():
        ws = tmp_path / "reset"
        _write_chunks(ws, {"r-1": _chunk("r-1", "要被清掉的块")})
        cfg = _cfg(ws)
        rag = await init_rag(cfg)
        try:
            assert (await rag.text_chunks.get_by_ids(["r-1"]))[0] is not None
            rag = await reset_rag(rag, cfg)
            chunks = await rag.text_chunks.get_by_ids(["r-1"])
            nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
            return chunks, nodes
        finally:
            await rag.finalize_storages()

    chunks, nodes = asyncio.run(run())
    assert chunks[0] is None, "块还留着：上个场景会污染下一个"
    assert nodes == []
