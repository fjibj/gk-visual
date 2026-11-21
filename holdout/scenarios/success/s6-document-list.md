---
{"fixture": "kb-small", "checks": [
  {"name": "文档列表列出两篇", "method": "GET", "url": "/api/documents",
   "expect": {"status": 200, "json": {"documents": {"$length": 2}}}},
  {"name": "张三那篇带实体统计", "method": "GET", "url": "/api/documents",
   "expect": {"status": 200, "json": {"documents": {"$any": {"doc_id": "doc-zhangsan", "entity_count": {"$gte": 1}}}}}}
]}
---

# 文档生命周期：列表与实体归属

**为什么有这一条**：文档面板的 `entity_count` / `relation_count` 是按 `source_id` 与块的
交集算出来的（`documents.py::_doc_entity_relation_counts`）。夹具建的时候就写入了真实
chunk id，所以这条同时验「文档→实体」的归属链没断。

**期望**：两篇文档；`doc-zhangsan` 至少贡献 1 个实体。
