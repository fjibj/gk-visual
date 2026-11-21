---
{"fixture": "kb-small", "checks": [
  {"name": "删不存在的文档", "method": "DELETE", "url": "/api/documents/no-such-doc",
   "expect": {"status": 404}},
  {"name": "删完之后库没被动过", "method": "GET", "url": "/api/documents",
   "expect": {"status": 200, "json": {"documents": {"$length": 2}}}}
]}
---

# 边界：删不存在的文档返回 404，且不误删别人的

**为什么有这一条**：删除是最危险的操作。误删没有容错余地，所以「删错了」必须报错，
而且库里别的东西不能受影响。

**期望**：DELETE 404；随后文档仍是两篇。
