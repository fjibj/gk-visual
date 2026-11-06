# M3 记录：Inline & Spill（注入/审计分离）

> 日期：2026-11-06
> 范围：`graphkb/memory_api.py`（`build_answer_context` / `MemoryTools.expand`）、`graphkb/mcp_server.py`（`memory.expand` 工具）
> 上游：M1 判据双文本、M2 MCP 面；下游：M5 三钩子（要靠这套预算说话）

## 1. 要解决的问题

M2 落地后，一次 `memory.search` 会把命中内容拼成 `answer_context` 交给 agent 注入。图小的时候没问题，但有一个必然要到来的天花板：

- 实体多、描述长（LightRAG 把同一实体的多次观察用 `<SEP>` 拼在一条 description 里，越用越长）；
- 块内容原样进上下文，一问能带出几百上千 token；
- 而 agent 的上下文窗口是有价格的。

两条错路都很熟：**全塞进去**（claude-mem 的死法，把 observation 一股脑糊进 prompt），或者**悄悄丢掉**（高亮还在、内容没了，调用方无从知道）。M3 要的是第三条路：**装得下的注入，装不下的留引用**。

## 2. 机制

```
命中实体/关系/块
   ↓ 归一成 Candidate{kind, ref, line, summary, tokens}
   ↓ 确定性排序：anchor → cited → path → 关系(direct 优先) → 块
   ↓ 贪心装填（预算 = max_context_tokens）
   ├─ 装得下 → inline，进 answer_context
   └─ 装不下 → spill_refs[{ref, kind, summary, tokens}]
                 ↓ 需要时
              memory.expand(refs) → 原文
```

三条硬规矩：

1. **注入内容只能从 Candidate 出**：零 LLM、可复算、顺序确定（同输入 → 同输出），排查时不靠运气。
2. **溢出不是丢弃**：`spill_refs` 带一行摘要（不占注入预算）和 token 代价，调用方自己判断值不值得取。
3. **摘要与正文分开计**：摘要进 JSON（agent 看得见），不占 `answer_context` 预算。

## 3. 关键决策：引用为什么是无状态的

候选方案有两个：

| 方案 | 做法 | 代价 |
|---|---|---|
| A. 进程内存 spill 表 | `spill-<8hex>` → 正文，LRU + TTL | 简单，但 server 一重启引用全失效；与 `job_id` 一样的短命问题 |
| B. **无状态引用**（采用） | `entity:张三` / `relation:A->B` / `chunk:c123` 直接指向图与块存储 | 重启/换会话照样能取；代价是「库里删了就取不到」 |

选 B 的理由：M2 已经有一个「进程内存」的债（`job_id` 表，重启即清空）。再叠一个同样短命的东西，意味着**引用能不能用取决于 server 活多久**——这种不确定对 agent 是最坏的一种，因为它没法判断。

B 的代价是诚实的、可检测的：目标不存在时 `expand` 回 `missing` + 原因，不编内容。

## 4. 实测（真图 17 实体 / 16 关系）

`budget.max_context_tokens = 120`：

```
context_used=103  context_inline=2  context_spilled=7  spilled_tokens=281
reason=budget_truncated
inline:  [anchor] 张三（person）…  [cited] 北京（location）…
spill:   entity:字节跳动(55)  relation:字节跳动->张三(34)  relation:北京->张三(19)
         chunk:doc-7286…-chunk-000(73)  chunk:S6验证文档-chunk-000(19)  等 7 条
expand  → 7 条全部取回，第 8 条（entity:根本不存在的人）如实报 missing
```

两个观察：

- LightRAG 的 description 里确实有 `<SEP>`（`一个人<SEP>张三是一位软件工程师…`），直出是天书；`expand` 时抖平成 `；` 再给。
- 关系引用的方向按图的边方向走（`字节跳动->张三`），跟文本里的语序不一致——调用方按 ref 原样回传即可，不要自己猜方向。

## 5. 边界

- token 是**粗估**（CJK 1 字 ≈ 1 token，ASCII 4 字符 ≈ 1 token），偏保守；换精确 tokenizer 是后话，真需要时再说。
- `expand` 单次最多 20 条、单条默认 2000 token 上限，超了标 `truncated=true`（而不是悄悄截断）。
- `hits` / `trace` 仍然完整返回（审计用）。它们**不注入**是调用方的责任——我们只保证 `answer_context` 是唯一"设计上给人注入"的东西。
- 溢出的块会保持检索给的原顺序，可能带上相关性一般的内容——这是检索层的问题，不是 M3 该盖的。

## 6. 测试

`tests/test_mcp.py` 覆盖：预算边界（恰好装下 / 少 1 token）、spill 引用形状与字段、`search → expand` 取回闭环、实体/关系/块三类引用、缺失引用（4 种失败原因）、输入校验（空 / 超 20 条 / 非法 max_tokens）、截断标记、`<SEP>` 抖平。

pytest：104 passed（全离线）。

## 7. 按层分配预算（2026-11-06 真图实测后补的）

小图上的 Inline & Spill 是「谁能装下谁进去」，因为总量本来就不紧张（17 实体那套图最多 9 行注入）。
真图（260 实体 / 371 关系）把它打回原形：**1 个锚点 + 2 个引用点 → 13 行注入里 10 行是 `[path]`**，
中间节点只是「这两个实体确实连得上」的证据，却和锚点抢同一份额度，把关系和块全挤去溢出。

改法（`LAYER_SHARES`，`graphkb/memory_api.py`）：

| 层 | 份额 | 形态 |
| --- | --- | --- |
| anchor | 40% | 名字 + 类型 + **完整描述**（截 240 字） |
| cited | 25% | 同上（证据层也是答案的一部分） |
| direct | 15% | 命中关系：两端都是锚点/引用点时带描述 |
| path | 12% | **只要名字 + 类型**（关系只留 `A -> B［关键词］`）；描述靠 `entity:` / `relation:` 取 |
| chunk | 8% | 原文，装不下就 spill |

两条配套规矩：

- **份额是软上限**：先算每层的真实需求，后面几层花不完的额度当前层可以先吃。否则「预算恰好够用」
  会被错杀——一个 60 token 的锚点配 60 的预算，按 40% 只给 24，当场溢出。
- **用不完的额度往下传**（waterfall），不平白浪费；每层花了多少记在 `budget_used.context_by_layer` 里。

实测（同一张真图、同样的 `max_context_tokens=800`）：

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| 1 锚 + 2 引用（`memory.search`） | inline 13 条 / 668 token，spill 3 块 / 1146 | inline **14** 条 / 692 token，spill **2** 块 / 764（1 块挤进来了） |
| 3 锚无引用 | inline 12 条 / 794，spill 12 / 3296 | inline **17** 条 / 735，spill **7** / 2674（实体与关系全进） |
| demo 真图 H1 起手查 | inline 9 条 / 797，spill 41 / 4380 | inline **34** 条 / 734，spill **16** / 2936 |

一句话：同样 800 token，装进去的条目多了将近四倍，路径层从「吃掉大半额度」变成「只占一两成」。

`degraded` 在真图上仍然是常态（块装不下就是 `budget_truncated`）——这是溢出不是丢弃，
但也说明默认 800 token 对 260 实体这种图偏紧，调大到多少算合适另有待定（见 backlog 18 的后续）。