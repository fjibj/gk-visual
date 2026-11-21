---
{"fixture": "kb-small", "checks": [
  {"name": "改实体描述", "method": "PATCH", "url": "/api/entities/张三",
   "body": {"description": "张三现在负责仓储调度系统"},
   "expect": {"status": 200, "json": {"name": "张三"}}},
  {"name": "改完读图能看到新描述", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$any": {"id": "张三", "description": {"$contains": "仓储调度系统"}}}}}}
]}
---

# 手工编辑：改实体描述，图立刻反映

**为什么有这一条**：这是「可手工编辑」的第一步——人能改，而且改了之后**读得回来**。
S5 验证过编辑会影响检索，但「改完图上看得到」这条一直只有肉眼验证。

**期望**：PATCH 返回 200；随后 GET /api/graph 里 `张三` 的 description 含新文本。
