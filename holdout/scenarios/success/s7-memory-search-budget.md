---
{"fixture": "kb-small", "checks": [
  {"name": "预算 200：注入不超过 200 token", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "张三在哪工作", "evidence_text": "张三在北京的云栈科技负责订单系统", "budget": 200},
   "expect": {"status": 200, "json": {"context_tokens": {"$lte": 200}}}},
  {"name": "预算 800：注入不超过 800 token", "method": "POST", "url": "/api/_test/memory_search",
   "body": {"question": "张三在哪工作", "evidence_text": "张三在北京的云栈科技负责订单系统", "budget": 800},
   "expect": {"status": 200, "json": {"context_tokens": {"$lte": 800}}}}
]}
---

# 预算守恒：小预算拿到的注入要更小

**为什么有这一条**：注入预算一旦不守恒，agent 的上下文就会悄悄超限——而超限的后果
（被截断、被丢中间段）在调用方看来像「模型变笨了」，极难归因。

**期望**：两个档位各自 ≤ 自己声明的预算；同时 `degraded` 不在断言里——预算紧会触发
`budget_truncated`，那是**正常行为**，不是缺陷。
