"""Success 3：未命中时得体返回「未找到」，不报错不编造。"""
from _common import run_with_client

NAME = "s3_no_hit_reports_not_found"
EXPECTATION = "Success 3: 未命中时 trace_hit=false 且答案含「未找到」"


async def run():
    def body(client):
        r = client.get("/api/query", params={"question": "任意问题"})
        b = r.json()
        ok = b["trace_hit"] is False and "未找到" in b["answer"]
        return ok, f"trace_hit={b['trace_hit']} answer={b['answer'][:30]!r}"

    return run_with_client(body)
