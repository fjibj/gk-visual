"""query.py 单元测试：trace 构建（纯函数）。"""

from __future__ import annotations

from graphkb.query import _build_trace


def test_build_trace_empty():
    t = _build_trace({}, {})
    assert t["entities"] == []
    assert t["relationships"] == []
    assert t["chunks"] == []


def test_build_trace_records_raw_retrieval():
    """retrieved 记下检索器捞到的全部，后面怎么分层都不动它。"""
    data = {
        "entities": [{"entity_name": "张三"}, {"entity_name": "北京"}],
        "relationships": [{"src_id": "北京", "tgt_id": "张三"}],
        "chunks": [],
    }
    t = _build_trace(data, {})
    assert t["retrieved"]["entity_count"] == 2
    assert t["retrieved"]["entities"] == ["张三", "北京"]
    assert t["retrieved"]["relationships"] == ["北京->张三"]


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
    # 检索原记录：不受后续高亮分层影响
    assert t["retrieved"] == {
        "entity_count": 1,
        "relation_count": 1,
        "entities": ["张三"],
        "relationships": ["张三->字节跳动"],
    }
    assert t["processing_info"]["total_entities_found"] == 1
