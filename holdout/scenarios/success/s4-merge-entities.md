---
{"fixture": "kb-small", "checks": [
  {"name": "把王敏合并进李雷", "method": "POST", "url": "/api/merge",
   "body": {"sources": ["王敏"], "target": "李雷"},
   "expect": {"status": 200, "json": {"target": "李雷"}}},
  {"name": "合并后节点少一个", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$length": 8}}}},
  {"name": "被合并掉的王敏不再作为节点存在", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$none": {"id": "王敏"}}}}}
]}
---

# 合并实体：源消失、目标留下

**为什么有这一条**：合并是 LightRAG 里最容易「只做一半」的操作——属性并进去、关系没改名、
源没删掉，肉眼看不出来。所以断两条：节点数从 9 变 8，且 `王敏` 真的不在了。

**期望**：merge 返回 200；图剩 8 个节点，`王敏` 不存在。
