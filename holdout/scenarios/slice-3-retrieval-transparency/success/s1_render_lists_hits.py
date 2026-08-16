"""Success 1：trace 有命中时渲染列出命中实体/关系（非黑盒）。"""
from graphkb.query import QueryResult
from graphkb.render import render

NAME = "s1_render_lists_hits"
EXPECTATION = "Success 1: trace 有命中时渲染列出命中实体/关系（不是黑盒答案）"


async def run():
    result = QueryResult(
        question="谁创立了字节跳动？",
        answer="张一鸣",
        trace={
            "keywords": {"high_level": ["创始人"], "low_level": ["字节跳动"]},
            "entities": [{"name": "字节跳动", "type": "organization", "score": 0.8}],
            "relationships": [{"src": "字节跳动", "tgt": "张一鸣", "score": 0.67}],
            "chunks": [],
        },
        trace_hit=True,
    )
    text = render(result)
    ok = "字节跳动" in text and "张一鸣" in text and "命中实体" in text and "命中关系" in text
    return ok, text.replace("\n", " | ")
