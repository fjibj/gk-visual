"""Success 4：检索是只读操作，不改变图。"""
from _common import run_with_client

NAME = "s4_query_is_readonly"
EXPECTATION = "Success 4: 检索不改变图（只读）"


async def run():
    def body(client):
        client.post("/api/entities", json={"name": "张三", "description": "工程师"})
        before = client.get("/api/graph").json()
        client.get("/api/query", params={"question": "任意问题"})
        after = client.get("/api/graph").json()
        ok = before == after
        return ok, f"检索前后图一致={before == after}"

    return run_with_client(body)
