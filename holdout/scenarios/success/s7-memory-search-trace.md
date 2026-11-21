---
{"fixture": "kb-small", "checks": [
  {"name": "Agent 面检索：锚点落在问题里的实体上", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "张三在哪工作", "evidence_text": "张三在北京的云栈科技负责订单系统", "budget": 800},
   "expect": {"status": 200, "json": {"anchors": {"$any": "张三"}, "trace_dangling_count": 0}}},
  {"name": "命中组件都真实存在于图上（无悬空引用）", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "李雷毕业于哪所大学", "evidence_text": "李雷毕业于南京大学", "budget": 800},
   "expect": {"status": 200, "json": {"cited": {"$any": "南京大学"}, "trace_dangling_count": 0}}}
]}
---

# S7 检索透明：锚点与证据层落在真实体上

**为什么有这一条**：这是整套项目的立身之本——「检索路径看得见，而且看得见的是真的」。
`/api/_test/memory_search` 背后就是 MCP 的同一个 `MemoryTools.search`，只是换了入口。

**期望**：
1. 问「张三在哪工作」→ 锚点含 `张三`；
2. 证据文本里点名「南京大学」→ 证据层含 `南京大学`；
3. 两次的 `trace_dangling_count` 都是 0（trace 引用的实体全部在图里）。

> 判断失败性质时先看 `trace_dangling_count`：它 > 0 说明是**实现**问题（悬空引用），
> 而 `anchors` 为空更像是**出题**问题（问题里没有字面实体名，锚点只能靠向量兜底）。
