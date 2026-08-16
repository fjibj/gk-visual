"""Success 2：trace 含 entities/relationships/chunks（前端高亮数据源）。"""
from _common import run_with_client

NAME = "s2_trace_shape_for_highlight"
EXPECTATION = "Success 2: trace 含 entities/relationships/chunks 且为 list"


async def run():
    def body(client):
        r = client.get("/api/query", params={"question": "任意问题"})
        trace = r.json()["trace"]
        ok = (
            isinstance(trace.get("entities"), list)
            and isinstance(trace.get("relationships"), list)
            and isinstance(trace.get("chunks"), list)
        )
        return ok, f"trace keys={sorted(trace.keys())}"

    return run_with_client(body)
