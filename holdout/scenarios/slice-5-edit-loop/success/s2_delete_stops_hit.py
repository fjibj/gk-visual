"""Success 2：删除实体 → 检索不再命中它。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "s2_delete_stops_hit"
EXPECTATION = "Success 2: 删除实体后检索不再命中该实体"


async def run():
    async def body(rag):
        q = "字节跳动总部在哪个城市"
        kw = ["字节跳动", "北京"]
        before = await query(rag, q, hl_keywords=kw)
        before_names = set(before.trace["retrieved"]["entities"])

        await rag.adelete_by_entity("北京")

        after = await query(rag, q, hl_keywords=kw)
        after_names = set(after.trace["retrieved"]["entities"])
        ok = "北京" in before_names and "北京" not in after_names
        return ok, f"编辑前={sorted(before_names)} 编辑后={sorted(after_names)}"

    return await run_with_rag(KG, body)
