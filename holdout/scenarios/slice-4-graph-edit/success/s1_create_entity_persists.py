"""Success 1：新建实体后重读图，实体确实存在。"""

from _common import run_with_client

NAME = "s1_create_entity_persists"
EXPECTATION = "Success 1: 创建实体 → 重读图可见该实体"


async def run():
    def body(client):
        r = client.post("/api/entities", json={"name": "新实体", "description": "描述"})
        if r.status_code != 201:
            return False, f"创建返回 {r.status_code}"
        g = client.get("/api/graph").json()
        ids = [n["id"] for n in g["nodes"]]
        return ("新实体" in ids), f"nodes={ids}"

    return run_with_client(body)
