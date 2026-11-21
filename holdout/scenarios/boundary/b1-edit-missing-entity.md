---
{"fixture": "kb-small", "checks": [
  {"name": "改不存在的实体", "method": "PATCH", "url": "/api/entities/子虚乌有",
   "body": {"description": "随便写点"},
   "expect": {"status": 404}}
]}
---

# 边界：改不存在的实体必须 404，不能静默成功

**为什么有这一条**：静默成功是「看不见的错」里最坏的一种——人手改完以为生效了，
其实什么都没发生，而检索结果因此和预期对不上。

**期望**：404（`server.py` 把 `aedit_entity` 的失败转成 404）。
