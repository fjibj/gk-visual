"""Success 3：合并实体后，源删除、目标保留。"""

from _common import run_with_client

NAME = "s3_merge_visible"
EXPECTATION = "Success 3: 合并 → 源实体删除、目标实体保留"


async def run():
    def body(client):
        client.post("/api/entities", json={"name": "源", "description": "s"})
        client.post("/api/entities", json={"name": "目标", "description": "t"})
        r = client.post("/api/merge", json={"sources": ["源"], "target": "目标"})
        if r.status_code != 200:
            return False, f"合并返回 {r.status_code}"
        g = client.get("/api/graph").json()
        ids = [n["id"] for n in g["nodes"]]
        ok = "源" not in ids and "目标" in ids
        return ok, f"nodes={ids}"

    return run_with_client(body)
