"""Boundary 2：变体不显式合并 → 保持原样（两个节点并存，不自动猜合并）。"""
from _common import MERGE_KG, entity_names, run_with_rag

NAME = "b2_variant_not_merged"
EXPECTATION = "Boundary 2: 变体不显式合并时保持原样（ByteDance 与 字节跳动 并存）"


async def run():
    async def body(rag):
        names = await entity_names(rag)
        both = "ByteDance" in names and "字节跳动" in names
        return both, f"entities={sorted(names)}"

    return await run_with_rag(MERGE_KG, body)
