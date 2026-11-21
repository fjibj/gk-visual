---
{"checks": [
  {"name": "空白内容被拒", "method": "POST", "url": "/api/documents",
   "body": {"title": "空文档", "content": "   "},
   "expect": {"status": 400}},
  {"name": "库里没多出东西", "method": "GET", "url": "/api/documents",
   "expect": {"status": 200, "json": {"documents": {"$length": 0}}}}
]}
---

# 边界：空白文档直接 400，不入库

**为什么有这一条**：空文档进库会走一次 30 秒的 LLM 抽取，什么也抽不出来，还污染文档列表。
S6 的 holdout 有同一条，这里是从 HTTP 面再验一次「拒绝发生在动手之前」。

**期望**：400；库仍是空的（连文档行都不该留）。
