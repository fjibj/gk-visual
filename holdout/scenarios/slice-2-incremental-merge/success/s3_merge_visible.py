"""Success 3：显式合并变体 → 源删除、关系转移、结果可见。"""
from graphkb.merge import merge_entities

from _common import MERGE_KG, entity_names, run_with_rag

NAME = "s3_merge_visible"
EXPECTATION = "Success 3: 显式合并变体后源删除、关系转移到目标、结果可见"


async def run():
    async def body(rag):
        r = await merge_entities(rag, ["ByteDance"], "字节跳动")
        names = await entity_names(rag)
        ok = (
            "ByteDance" not in names
            and r.relationships_transferred >= 1
            and r.sources_remaining == []
        )
        detail = f"transferred={r.relationships_transferred} entities={sorted(names)}"
        return ok, detail

    return await run_with_rag(MERGE_KG, body)
