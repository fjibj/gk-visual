"""Boundary 2：检索与健康检查路由共存，无冲突。"""
from _common import run_with_client

NAME = "b2_query_health_coexist"
EXPECTATION = "Boundary 2: /api/query 与 /api/health 共存"


async def run():
    def body(client):
        h = client.get("/api/health")
        q = client.get("/api/query", params={"question": "任意问题"})
        ok = h.status_code == 200 and q.status_code == 200
        return ok, f"health={h.status_code} query={q.status_code}"

    return run_with_client(body)
