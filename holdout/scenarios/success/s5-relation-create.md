---
{"fixture": "kb-small", "checks": [
  {"name": "新建关系 张三 → 成都", "method": "POST", "url": "/api/relations",
   "body": {"source": "张三", "target": "成都", "description": "张三每月去成都分部出差", "keywords": "出差"},
   "expect": {"status": 201}},
  {"name": "图上出现这条边", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"edges": {"$length": 13}}}},
  {"name": "边的一端是张三、另一端是成都", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"edges": {"$any": {"source": "张三", "target": "成都"}}}}}
]}
---

# 手工建关系：两个已有实体之间加边

**为什么有这一条**：S4 的 CRUD 里，「建关系」是最少被复测的一条（UI 上点两下就成了，
没人验过它真的落到图里）。夹具里 `张三` 与 `成都` 原本不相连。

**期望**：POST 201；边数 12 → 13；存在 `张三 → 成都`。
