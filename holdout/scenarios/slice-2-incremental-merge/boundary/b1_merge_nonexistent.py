"""Boundary 1：合并不存在的实体 → 图不变、不崩溃（报错或 no-op 均可，但不得破坏图）。"""
from graphkb.merge import merge_entities

from _common import MERGE_KG, entity_names, run_with_rag

NAME = "b1_merge_nonexistent"
EXPECTATION = "Boundary 1: 合并不存在的实体，图保持不变、不崩溃"


async def run():
    async def body(rag):
        before = sorted(await entity_names(rag))
        try:
            await merge_entities(rag, ["不存在的实体X"], "字节跳动")
            raised = False
        except Exception:
            raised = True
        after = sorted(await entity_names(rag))
        unchanged = before == after
        return unchanged, f"raised={raised} before={before} after={after}"

    return await run_with_rag(MERGE_KG, body)
