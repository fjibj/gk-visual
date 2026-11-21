---
{"fixture": "kb-small", "checks": [
  {"name": "读图：夹具的 9 个节点 / 12 条边都在", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$length": 9}, "edges": {"$length": 12}}}},
  {"name": "张三在图上，且带 M4 溯源标签", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$any": {"id": "张三", "origin": {"$exists": true}}}}}}
]}
---

# 读图：图与节点属性如实返回

**为什么有这一条**：`GET /api/graph` 是前端和溯源的地基。它挂掉的话，后面所有「看见图」
的说法都不成立。夹具 `kb-small` 是固定的 9 实体 / 12 关系，所以长度断言是确定的。

**期望**：9 个节点、12 条边；`张三` 带 `origin`（M4 那套 extracted/manual/mixed/unknown）。
