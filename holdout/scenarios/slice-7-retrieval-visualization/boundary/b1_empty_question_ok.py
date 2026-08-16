"""Boundary 1：空问题不崩溃（得体返回）。"""
from _common import run_with_client

NAME = "b1_empty_question_ok"
EXPECTATION = "Boundary 1: 空问题得体返回，不崩溃"


async def run():
    def body(client):
        r = client.get("/api/query", params={"question": ""})
        return r.status_code == 200, f"status={r.status_code}"

    return run_with_client(body)
