"""Failure 2：抽取不出实体的文档 → 得体处理（不崩溃），报告未抽取到实体。"""
from _common import run_with_rag
from graphkb.ingest import ingest_document

NAME = "f2_no_entity_doc"
EXPECTATION = "Failure 2: 无实体文档得體处理，实体数为0（不崩溃）"


async def run():
    async def body(rag):
        # mock LLM 返回 "mock-response"，无法抽取任何实体 → 应得體返回 0
        res = await ingest_document(rag, "mock LLM 无法抽取任何实体的任意文本")
        return (res.entity_count == 0), f"entity_count={res.entity_count} relation_count={res.relation_count}"

    return await run_with_rag(None, body)
