"""Boundary 2：删除实体后，其孤儿关系一并清理（不留残边）。"""

from _common import run_with_client

NAME = "b2_delete_entity_cleans_relations"
EXPECTATION = "Boundary 2: 删实体 → 其关系一并清理，无孤儿边"


async def run():
    def body(client):
        client.post("/api/entities", json={"name": "A", "description": "a"})
        client.post("/api/entities", json={"name": "B", "description": "b"})
        client.post("/api/relations", json={"source": "A", "target": "B", "description": "关联"})
        client.delete("/api/entities/A")
        g = client.get("/api/graph").json()
        edges = [(e["source"], e["target"]) for e in g["edges"]]
        return edges == [], f"edges after delete={edges}"

    return run_with_client(body)
