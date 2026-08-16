"""Boundary 2：编辑与检索问题无关的实体 → 该问题命中集不变（不误伤）。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "b2_unrelated_edit_no_side_effect"
EXPECTATION = "Boundary 2: 编辑无关实体不影响无关检索路径"


async def run():
    async def body(rag):
        q = "字节跳动总部在哪个城市"
        kw = ["字节跳动", "北京"]
        before = await query(rag, q, hl_keywords=kw)
        before_names = {e["name"] for e in before.trace["entities"]}

        # 编辑与该问题无关的实体（张三）
        await rag.aedit_entity("张三", {"description": "数据科学家"})

        after = await query(rag, q, hl_keywords=kw)
        after_names = {e["name"] for e in after.trace["entities"]}
        unchanged = before_names == after_names
        return unchanged, f"编辑前={sorted(before_names)} 编辑后={sorted(after_names)}"

    return await run_with_rag(KG, body)
