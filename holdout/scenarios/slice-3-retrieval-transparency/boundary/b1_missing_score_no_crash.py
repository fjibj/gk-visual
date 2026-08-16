"""Boundary 1：命中实体在向量库查不到分数 → 标注无分数、不崩溃。"""
from graphkb.query import _score_trace

from _common import KG, run_with_rag

NAME = "b1_missing_score_no_crash"
EXPECTATION = "Boundary 1: 命中实体查不到分数时标注无分数、不崩溃"


async def run():
    async def body(rag):
        trace = {"entities": [{"name": "不存在的实体XYZ"}], "relationships": []}
        out = await _score_trace(rag, "完全不相关的查询", trace)
        score = out["entities"][0]["score"]
        return score is None, f"score={score}"

    return await run_with_rag(KG, body)
