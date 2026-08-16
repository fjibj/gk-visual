"""query.py 单元测试：trace 构建（纯函数）。"""

from __future__ import annotations

from graphkb.query import _build_trace


def test_build_trace_empty():
    t = _build_trace({}, {})
    assert t["entities"] == []
    assert t["relationships"] == []
    assert t["chunks"] == []


def test_build_trace_shapes():
    data = {
        "entities": [{"entity_name": "张三", "entity_type": "person", "description": "x"}],
        "relationships": [
            {"src_id": "张三", "tgt_id": "字节跳动", "description": "y", "keywords": "任职", "weight": 1.0}
        ],
        "chunks": [{"content": "z", "chunk_id": "c1"}],
    }
    metadata = {
        "query_mode": "mix",
        "keywords": {"high_level": ["a"], "low_level": ["b"]},
        "processing_info": {"total_entities_found": 1},
    }
    t = _build_trace(data, metadata)
    assert t["query_mode"] == "mix"
    assert t["keywords"] == {"high_level": ["a"], "low_level": ["b"]}
    assert t["entities"] == [{"name": "张三", "type": "person", "description": "x"}]
    assert t["relationships"][0] == {
        "src": "张三",
        "tgt": "字节跳动",
        "description": "y",
        "keywords": "任职",
        "weight": 1.0,
    }
    assert t["chunks"] == [{"content": "z", "chunk_id": "c1"}]
    assert t["processing_info"]["total_entities_found"] == 1
