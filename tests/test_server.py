"""server.py 的 FastAPI 层测试：编辑落库（改后重读图生效）+ 错误分支。

全 mock（mock LLM + mock embedding dim=64），离线确定性，无外部依赖。
编辑操作复用 LightRAG 编辑 API，断言"改后重读图"确实生效（S4 验收点 3）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from graphkb.server import create_app


def make_client(mock_config):
    app = create_app(config=mock_config)
    return TestClient(app)


def test_health(mock_config):
    with make_client(mock_config) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_graph_empty(mock_config):
    with make_client(mock_config) as client:
        g = client.get("/api/graph").json()
        assert g["nodes"] == []
        assert g["edges"] == []


def test_create_entity(mock_config):
    with make_client(mock_config) as client:
        r = client.post("/api/entities", json={"name": "张三", "type": "person", "description": "工程师"})
        assert r.status_code == 201
        g = client.get("/api/graph").json()
        assert [n["id"] for n in g["nodes"]] == ["张三"]


def test_edit_entity_persists(mock_config):
    with make_client(mock_config) as client:
        client.post("/api/entities", json={"name": "张三", "type": "person", "description": "原描述"})
        r = client.patch("/api/entities/张三", json={"description": "新描述"})
        assert r.status_code == 200
        g = client.get("/api/graph").json()
        node = next(n for n in g["nodes"] if n["id"] == "张三")
        assert node["description"] == "新描述"


def test_edit_missing_entity(mock_config):
    with make_client(mock_config) as client:
        r = client.patch("/api/entities/不存在", json={"description": "x"})
        assert r.status_code == 404


def test_delete_entity_removes_relations(mock_config):
    with make_client(mock_config) as client:
        client.post("/api/entities", json={"name": "A", "description": "a"})
        client.post("/api/entities", json={"name": "B", "description": "b"})
        client.post("/api/relations", json={"source": "A", "target": "B", "description": "关联"})
        r = client.delete("/api/entities/A")
        assert r.status_code == 200
        g = client.get("/api/graph").json()
        assert [n["id"] for n in g["nodes"]] == ["B"]
        assert g["edges"] == []  # 孤儿关系一并清理


def test_delete_missing_entity(mock_config):
    with make_client(mock_config) as client:
        r = client.delete("/api/entities/不存在")
        assert r.status_code == 404


def test_create_and_delete_relation(mock_config):
    with make_client(mock_config) as client:
        client.post("/api/entities", json={"name": "A"})
        client.post("/api/entities", json={"name": "B"})
        r = client.post("/api/relations", json={"source": "A", "target": "B", "description": "关联", "keywords": "kw"})
        assert r.status_code == 201
        g = client.get("/api/graph").json()
        assert (g["edges"][0]["source"], g["edges"][0]["target"]) == ("A", "B")

        r = client.delete("/api/relations", params={"source": "A", "target": "B"})
        assert r.status_code == 200
        assert client.get("/api/graph").json()["edges"] == []


def test_delete_missing_relation(mock_config):
    with make_client(mock_config) as client:
        client.post("/api/entities", json={"name": "A"})
        client.post("/api/entities", json={"name": "B"})
        r = client.delete("/api/relations", params={"source": "A", "target": "B"})
        assert r.status_code == 404


def test_merge_entities(mock_config):
    with make_client(mock_config) as client:
        client.post("/api/entities", json={"name": "源", "description": "s"})
        client.post("/api/entities", json={"name": "目标", "description": "t"})
        r = client.post("/api/merge", json={"sources": ["源"], "target": "目标"})
        assert r.status_code == 200
        g = client.get("/api/graph").json()
        assert [n["id"] for n in g["nodes"]] == ["目标"]
