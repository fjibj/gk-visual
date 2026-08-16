"""Boundary 1：孤立实体（无关系）不被 dual-level 检索召回（LightRAG 固有边界）。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "b1_isolated_entity_not_recalled"
EXPECTATION = "Boundary 1: 孤立实体不被 dual-level 检索召回（已知边界，锁定此行为）"


async def run():
    async def body(rag):
        await rag.acreate_entity("上海", {"entity_type": "location", "description": "中国直辖市"})

        r = await query(rag, "上海是什么", hl_keywords=["上海"])
        names = {e["name"] for e in r.trace["entities"]}
        # 已知边界：孤立节点无邻居，图遍历扩展不到 → 不召回。锁定此行为，防无感知回归。
        return ("上海" not in names), f"孤立上海召回={'上海' in names}，命中={sorted(names)}"

    return await run_with_rag(KG, body)
