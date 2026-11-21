---
{"fixture": "kb-small", "checks": [
  {"name": "删掉张三那篇文档", "method": "DELETE", "url": "/api/documents/doc-zhangsan",
   "expect": {"status": 200, "json": {"status": "success"}}},
  {"name": "文档列表只剩一篇", "method": "GET", "url": "/api/documents",
   "expect": {"status": 200, "json": {"documents": {"$length": 1}}}},
  {"name": "只属于这篇文档的张三从图上消失", "method": "GET", "url": "/api/graph",
   "expect": {"status": 200, "json": {"nodes": {"$none": {"id": "张三"}}}}}
]}
---

# 文档删除：图要跟着收敛

**为什么有这一条**：S6 的核心承诺是「删文档 → 由它独占的实体跟着消失，共享的不动」。
夹具里 `张三` 的 `source_id` 只指向 `doc-zhangsan` 的块，所以删完必须没有 `张三`。

**期望**：DELETE 200 → 文档剩 1 篇 → 图上查不到 `张三`。

> 若第三条在 observe 里红了而前两条绿，先怀疑夹具的 `source_id` 归属，而不是实现。
