"""Success 1：/api/query 返回 answer + trace + trace_hit。"""
from _common import run_with_client

NAME = "s1_query_returns_structure"
EXPECTATION = "Success 1: /api/query 返回 answer/trace/trace_hit 结构"


async def run():
    def body(client):
        r = client.get("/api/query", params={"question": "任意问题"})
        if r.status_code != 200:
            return False, f"返回 {r.status_code}"
        b = r.json()
        ok = set(b.keys()) >= {"answer", "trace", "trace_hit"}
        return ok, f"keys={sorted(b.keys())}"

    return run_with_client(body)
