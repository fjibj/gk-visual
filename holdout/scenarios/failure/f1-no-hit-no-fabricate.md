---
{"fixture": "kb-small", "checks": [
  {"name": "问库里没有的东西：注入为空", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "火星殖民地的氧气批发价是多少", "evidence_text": "我们没有任何关于火星的记录", "budget": 800},
   "expect": {"status": 200, "json": {"context_chars": 0}}},
  {"name": "并且如实标记为降级查询", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "火星殖民地的氧气批发价是多少", "evidence_text": "我们没有任何关于火星的记录", "budget": 800},
   "expect": {"status": 200, "json": {"degraded": true}}}
]}
---

# 失败面：查不到就交白卷，绝不编造

**为什么有这一条**：整个项目的 Failure Condition 里最硬的一条是「不编造」。当问题里
没有库内任何实体时，正确行为是**交空上下文并说清为什么**，而不是拿向量召回的相似块
凑一段看起来有据可依的内容。

**期望**：`context_chars == 0`（注入为空）且 `degraded == true`（带 reason，说明是
`no_anchor` 还是别的）。

> 这条在 observe 里如果只红第一条，先看 `reason`：可能是向量兜底真召回了一个实体——
> 那是「话题相似」而不是「实体相关」，属实现问题（S7 那条不变量）。
