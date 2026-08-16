"""Success 3：渲染展示 dual-level 链条（高层→低层→实体→块）。"""
from graphkb.query import QueryResult
from graphkb.render import render

NAME = "s3_dual_level_visible"
EXPECTATION = "Success 3: 渲染展示 dual-level 链条（高层关键词→低层实体→依据块）"


async def run():
    result = QueryResult(
        question="q",
        answer="a",
        trace={
            "keywords": {"high_level": ["创始人"], "low_level": ["字节跳动"]},
            "entities": [{"name": "字节跳动", "score": 0.5}],
            "relationships": [],
            "chunks": [{"content": "块内容"}],
        },
        trace_hit=True,
    )
    text = render(result)
    ok = "高层" in text and "低层" in text and "命中实体" in text and "依据块" in text
    return ok, text.replace("\n", " | ")
