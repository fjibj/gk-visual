"""Success 2：两批含同名实体 → 同名合并为单节点。"""
from _common import BATCH_A, BATCH_C_overlap, entity_names, run_with_rag

NAME = "s2_same_name_single_node"
EXPECTATION = "Success 2: 同名实体（字节跳动）跨批次合并为一个节点"


async def run():
    async def body(rag):
        names = await entity_names(rag)
        count = names.count("字节跳动")
        ok = count == 1
        return ok, f"字节跳动出现 {count} 次，全图 {sorted(names)}"

    return await run_with_rag([BATCH_A, BATCH_C_overlap], body)
