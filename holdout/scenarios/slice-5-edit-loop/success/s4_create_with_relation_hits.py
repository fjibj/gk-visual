"""Success 4：新建实体（连同关系）→ 检索可命中。"""
from _common import KG, run_with_rag
from graphkb.query import query

NAME = "s4_create_with_relation_hits"
EXPECTATION = "Success 4: 新建实体+关系后检索可命中新增内容"


async def run():
    async def body(rag):
        await rag.acreate_entity("上海", {"entity_type": "location", "description": "中国直辖市"})
        await rag.acreate_relation("字节跳动", "上海", {"description": "总部位于上海", "keywords": "总部"})

        r = await query(rag, "字节跳动总部在哪", hl_keywords=["字节跳动", "上海"])
        names = set(r.trace["retrieved"]["entities"])
        rels = set(r.trace["retrieved"]["relationships"])
        ok = "上海" in names and ("字节跳动->上海" in rels or "上海->字节跳动" in rels)
        return ok, f"命中实体={sorted(names)} 命中关系={sorted(rels)}"

    return await run_with_rag(KG, body)
