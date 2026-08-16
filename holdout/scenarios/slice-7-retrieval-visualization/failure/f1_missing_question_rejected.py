"""Failure 1：缺 question 参数 → 拒绝（422）。"""
from _common import run_with_client

NAME = "f1_missing_question_rejected"
EXPECTATION = "Failure 1: 缺 question 参数被拒绝"


async def run():
    def body(client):
        r = client.get("/api/query")
        return r.status_code == 422, f"status={r.status_code}"

    return run_with_client(body)
