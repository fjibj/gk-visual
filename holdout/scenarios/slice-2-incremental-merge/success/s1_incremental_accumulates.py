"""Success 1：两批无重叠并入 → 图累积，第一批实体不消失。"""
from _common import BATCH_A, BATCH_B_disjoint, entity_names, run_with_rag

NAME = "s1_incremental_accumulates"
EXPECTATION = "Success 1: 第二篇并入后图累积（并集），第一篇实体不消失"


async def run():
    async def body(rag):
        names = await entity_names(rag)
        expected = {"张三", "字节跳动", "李四", "北京"}
        ok = expected <= set(names)
        return ok, f"entities={sorted(names)}"

    return await run_with_rag([BATCH_A, BATCH_B_disjoint], body)
