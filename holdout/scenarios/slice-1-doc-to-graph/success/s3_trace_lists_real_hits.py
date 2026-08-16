"""Success 3：trace 列出命中实体/关系，且这些确实在图里存在（不编造）。"""
from _common import ENTITY_NAMES, KG, run_with_rag
from graphkb.query import query

NAME = "s3_trace_lists_real_hits"
EXPECTATION = "Success 3: trace 列出命中实体/关系，且均为图中真实存在的（不编造）"


async def run():
    async def body(rag):
        r = await query(rag, "字节跳动的总部在哪里？", hl_keywords=["字节跳动"], ll_keywords=["字节跳动"])
        entities = [e["name"] for e in r.trace["entities"]]
        relationships = r.trace["relationships"]
        hit_names_ok = set(entities) <= set(ENTITY_NAMES)
        passed = bool(entities) and bool(relationships) and hit_names_ok
        rels = [(x["src"], x["tgt"]) for x in relationships]
        return passed, f"entities={entities} relations={rels}"

    return await run_with_rag(KG, body)
