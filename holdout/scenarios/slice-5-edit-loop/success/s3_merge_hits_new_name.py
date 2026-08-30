"""Success 3：合并实体 → 检索命中新名、不再命中旧名。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "s3_merge_hits_new_name"
EXPECTATION = "Success 3: 合并后检索命中新名、不命中旧名"


async def run():
    async def body(rag):
        q = "张三在哪个城市工作"
        await rag.amerge_entities(source_entities=["张三"], target_entity="李四")

        after = await query(rag, q, hl_keywords=["李四", "字节跳动", "北京"])
        names = set(after.trace["retrieved"]["entities"])
        ok = "李四" in names and "张三" not in names
        return ok, f"合并后命中实体={sorted(names)}"

    return await run_with_rag(KG, body)
