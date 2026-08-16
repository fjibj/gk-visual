"""Success 2：真实向量库查询给命中实体补上 0~1 余弦分数。"""
from graphkb.query import _score_trace

from _common import KG, run_with_rag

NAME = "s2_scores_present"
EXPECTATION = "Success 2: 命中实体有真实余弦分数（0~1）"


async def run():
    async def body(rag):
        trace = {
            "entities": [{"name": "字节跳动"}, {"name": "张三"}],
            "relationships": [{"src": "张三", "tgt": "字节跳动"}],
        }
        out = await _score_trace(rag, "字节跳动", trace)
        scores = [e.get("score") for e in out["entities"]]
        has = any(s is not None for s in scores)
        in_range = all(0.0 <= s <= 1.0 for s in scores if s is not None)
        return (has and in_range), f"scores={scores}"

    return await run_with_rag(KG, body)
