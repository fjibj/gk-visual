"""Failure 1：编辑不存在的实体必须显式报错（404），不静默。"""

from _common import run_with_client

NAME = "f1_edit_missing_reports"
EXPECTATION = "Failure 1: 编辑不存在的实体 → 显式 404，不改图"


async def run():
    def body(client):
        r = client.patch("/api/entities/不存在", json={"description": "x"})
        return r.status_code == 404, f"status={r.status_code}"

    return run_with_client(body)
