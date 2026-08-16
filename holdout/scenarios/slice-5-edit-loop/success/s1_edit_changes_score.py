"""Success 1：编辑实体描述 → 检索 trace 中该实体描述变化。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "s1_edit_changes_score"
EXPECTATION = "Success 1: 编辑实体描述后检索 trace 中该实体描述变化"


async def run():
    async def body(rag):
        q = "张三在哪个城市工作"
        kw = ["张三", "字节跳动", "北京"]
        before = await query(rag, q, hl_keywords=kw)
        before_desc = {e["name"]: e["description"] for e in before.trace["entities"]}

        await rag.aedit_entity("张三", {"description": "数据科学家，专注推荐系统"})

        after = await query(rag, q, hl_keywords=kw)
        zs = next((e for e in after.trace["entities"] if e["name"] == "张三"), None)
        changed = zs is not None and zs["description"] != before_desc.get("张三")
        score = zs.get("score") if zs else None
        return changed, f"张三 desc {before_desc.get('张三')!r} -> {zs['description'] if zs else None!r}，score={score}"

    return await run_with_rag(KG, body)
