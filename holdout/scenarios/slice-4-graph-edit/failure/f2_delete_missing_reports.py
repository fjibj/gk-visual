"""Failure 2：删除不存在的实体必须显式报错（404），不静默。"""

from _common import run_with_client

NAME = "f2_delete_missing_reports"
EXPECTATION = "Failure 2: 删除不存在的实体 → 显式 404，不改图"


async def run():
    def body(client):
        r = client.delete("/api/entities/不存在")
        return r.status_code == 404, f"status={r.status_code}"

    return run_with_client(body)
