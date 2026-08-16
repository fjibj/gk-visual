"""Boundary 1：空图读图返回空列表，不崩溃。"""

from _common import run_with_client

NAME = "b1_empty_graph_ok"
EXPECTATION = "Boundary 1: 空图 → nodes/edges 为空列表，不崩溃"


async def run():
    def body(client):
        g = client.get("/api/graph").json()
        return (g["nodes"] == [] and g["edges"] == []), (
            f"nodes={len(g['nodes'])} edges={len(g['edges'])}"
        )

    return run_with_client(body)
