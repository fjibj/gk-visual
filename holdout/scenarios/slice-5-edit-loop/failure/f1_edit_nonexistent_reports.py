"""Failure 1：编辑不存在的实体 → 报错，且图不被污染。"""
from _common import KG, run_with_rag

NAME = "f1_edit_nonexistent_reports"
EXPECTATION = "Failure 1: 编辑不存在的实体必须显式报错且不污染图"


async def run():
    async def body(rag):
        try:
            await rag.aedit_entity("不存在的实体", {"description": "x"})
            return False, "编辑不存在的实体未报错"
        except Exception as exc:  # noqa: BLE001
            nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
            names = {n.get("entity_id") for n in nodes}
            clean = "张三" in names and "不存在的实体" not in names
            return clean, f"报错={type(exc).__name__}，张三仍在={('张三' in names)}"

    return await run_with_rag(KG, body)
