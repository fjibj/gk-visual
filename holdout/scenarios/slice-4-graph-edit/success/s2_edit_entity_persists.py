"""Success 2：编辑实体描述后重读图，描述已更新（落库）。"""

from _common import run_with_client

NAME = "s2_edit_entity_persists"
EXPECTATION = "Success 2: 编辑描述 → 重读图描述已更新"


async def run():
    def body(client):
        client.post("/api/entities", json={"name": "张三", "description": "原描述"})
        r = client.patch("/api/entities/张三", json={"description": "改后描述"})
        if r.status_code != 200:
            return False, f"编辑返回 {r.status_code}"
        g = client.get("/api/graph").json()
        node = next(n for n in g["nodes"] if n["id"] == "张三")
        return node["description"] == "改后描述", f"desc={node['description']}"

    return run_with_client(body)
