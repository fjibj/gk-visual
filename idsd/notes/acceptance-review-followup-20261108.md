# 外部验收报告的复核与跟改（2026-11-08）

> 起因：小C《gk-visual M0–M6 验收报告（2026-11-08）》——「逐条核验 + 优化清单」
> 范围：`graphkb/memory_api.py`、`graphkb/mcp_server.py`、`scripts/preflight.py`、`tests/test_mcp.py`、`tests/test_real_graph.py`
> 结论：报告的对账部分扎实，但它列的三条「真问题」里两条用的是**修复之前**的数据、一条**修法不对症**。照它的清单做会白花力气。

## 1. 报告的判定与复核结果

| 报告项 | 判定 | 依据 |
| --- | --- | --- |
| M0–M6 逐条对账、提交号、tag | ✅ 全对 | 复核 git 历史 |
| 「三处超出计划」（`memory.expand` / 分层预算 / 真图回归） | ✅ 全对，判断也准 | — |
| P0-1 `path` 仍是大头（「13 行注入 10 行 path，挤占实体描述」） | ❌ 数字是旧的 | 13 行 / 10 行 / 668 token 是 `4076bc7`（按层分预算）**之前**的数；报告自己在第 2 节把这次改动夸了一遍，第 3 节又用改动前的数据当 P0 |
| P0-2 `job` 状态在内存，建议落 SQLite | ⚠️ 问题真、修法不对症 | 活儿不会丢（LightRAG 自动续跑），丢的只是票；状态真值已在 `doc_status` 磁盘上 |
| P1 `origin` 只回显不落库（「backlog#9 只完成一半」） | ⚠️ 范围判断有误 | #9 是「这条事实从哪来」，已交付；「谁在何时改的」是新需求（审计日志）。且外挂表会被 S4 合并 / S5 改名删成孤儿 |
| 提醒①：token 粗估让注入偏少 | ❌ 方向反了 | 实测混排文本粗估**少算**约 11%，不是多算 |
| 提醒②：CI 不覆盖 holdout | ✅ 问题真，解法做不到 | holdout 要真 LLM + 真 embedding，塞 key 违反安全底线 |

## 2. 复核用的实测（不是回忆）

```
80 实体夹具（回放，零 LLM）  1 锚 + 2 引用：
  改前（分层之后）: anchor 1/44 · cited 2/143 · path 10/123 · chunk 1/382 = 14 行 / 692 token
  改后（本轮）    : anchor 1/44 · cited 2/143 · path  6/ 91 · chunk 1/382 = 10 行 / 649 token
  path 的 token 份额一直是 14~18%，从来不是「挤占实体描述」的那一层（块拿 55~58%）

260 实体真图（`ab8c865` 时实测，记在 m3-inline-spill §8）：38 行 / 1158 token，
  其中 anchor 451、path 438、cited 0、direct 33、chunk 236 —— path 占额 38%，行数 84%。

estimate_tokens vs cl100k：纯中文 30 字 → 粗估 30 / 实际 30；106 字 → 99 / 100；
  带标识符的整段注入 952 字 → 粗估 676 / 实际 758（少算 11%）。
```

## 3. 改动一：任务票跨进程（P7）

**问题**：MCP 是 stdio，**每个 agent 会话就是一个新进程**——`job_id` 靠内存活不过去（比报告说的「偶尔重启」更硬）。

**关键判断**：丢的不是活儿，是票。LightRAG 1.5.7 的 pipeline 对 `pending/processing/parsing/analyzing` 有 `_AUTO_RESUME_DOC_STATUSES`（`lightrag/pipeline.py`），`doc_status` 也在磁盘上。

**现场验证**（`scripts/verify_job_resume.py`，真 LLM + 真库副本，四段各一个进程）：

```
prepare  → 复制 data/ 成实验库
ingest   → 异步写一篇 6 段文档（21 实体 / 30 关系），跑到 "Writing graph" 时强杀进程
status   → 新进程：内存票 {}，落盘票有 doc_id；doc_status 盘上 = processing
           ingest_status → status=running, progress=正在写图/写向量, status_source=store
resume   → 新进程写一篇小文档，日志出现：
           "Completed processing file 1/2: 中断实验文档-…"   ← 被中断那篇被自动续跑并完成
```

**落地**（`graphkb/memory_api.py`）：

- `ingest` 建票即落盘：`working_dir/mcp_jobs[.<workspace>].json`，原子写（tmp + `os.replace`），上限 `JOB_RETENTION=200`（先丢已完成），写盘失败只记日志不阻断写入。
- `ingest_status` 改 async、两级来源：本进程票据 → 落盘票据 + `rag.doc_status.get_by_id(doc_id)`；回 `status_source`（`process`/`store`）与 `doc_status`（库上原状态）。词表仍是 `queued|running|done|error|unknown`，阶段放 `progress`。
- 为什么不用 SQLite：票据只是一层映射，状态真值在 LightRAG 那边；SQLite 要多一份一致性、迁移与生命周期，收益为零。

**现场撞出来的真 bug**：`doc_status` 行在进程内是新写的 `DocStatus` **枚举**，从盘上读回来才是字符串。`str(DocStatus.PROCESSED)` = `"DocStatus.PROCESSED"`，与词表对不上 → 误报 `unknown`。修法：`getattr(v, "value", None) or str(v)`，并用 `test_job_status_accepts_enum_doc_status` 钉住。

## 4. 改动二：path 层只出关系行

**依据**：中间节点的唯一作用是证明「锚点和引用点连得上」，这件事 `[path] A -> B［关键词］` 已经说完了；单列一行「名字（类型）」是重复。真图上那 4 行（80 夹具）/ 8~10 行（260 图）每一行都在消耗模型的注意力，却只重复了关系行里已有的名字。

**不变量（去掉的前提）**：路径上每一条跳边都会成为关系行（`hit_relationships` 来自全图邻接 `rel_by_key`），所以每个中间节点至少出现在一条关系行的两端——`test_path_entities_are_visible_through_relation_lines` 钉住这条。

**反证**（就写在同一个用例里）：把注入里的 path 关系行全删，4 个中间节点（`symbol_34` / `条目222` / `条目225` / `条目49`）全部从可见集合里消失 → 这条断言不是空的。

**为什么不采纳报告的三个建议**：
1. 「没有 direct 边才展开 path」——砍掉连通性证据，而「一题 = 若干连通簇」是 2026-08-30 定的不变量，不能拿它换预算；
2. 「只留起终点」——现在本来就是（中间节点才是 path 层）；
3. 「压成一句摘要」——丢掉每个节点的类型，且与前端 S7 的分层信息不再一一对应。

## 5. 改动三：本地 preflight（对应「CI 不覆盖 holdout」）

`scripts/preflight.py`：离线测试 → 现场测试（`-m slow`，真库副本 + 真模型）→ 指定切片 holdout → 前端构建 → git 体检（脏工作树 / 未推提交 / HEAD 上的 tag），末了一张 PASS/FAIL 表，有失败退出码 1。

已实测：`--holdout slice-3-retrieval-transparency --holdout-version preflight-smoke` → **7/7**（结果目录跑完即清）。

分工写清了：CI 管离线那一半（每次 push），preflight 管需要模型/真库那一半（签收前本机跑）。S3 holdout 腐烂 12 天不是「没放 CI」，是「改签名时没人跑」。

## 6. 明确没做的

| 项 | 为什么不做 |
| --- | --- |
| `job` 落 SQLite | 状态真值在 `doc_status`，多一层存储只是多一份要维护的副本 |
| `origin` 落库 + 变更历史 | 外挂表按实体名做键，会被 S4 合并、S5 改名/删除弄成孤儿；要活下来得在三条写路径上挂钩子 → 给「人能改图」加耦合，撞约束 6。等真有人（有 agent）在图上手改再设计 |
| token 精确计数 | 误差方向取决于调用方 tokenizer（cl100k 少算 11% / Qwen 类多算），引依赖换不来确定性 |
| Guarded 检索缓存 | 报告的结论（先压 path 再缓存）对，理由是就绪度：现在缓存下来的是还没调过的注入 |

## 7. 数字与命令

- `pytest -q` → **203 passed**（201 离线 + 2 条 slow 现场）；`-m "not slow"` → 201 passed / 2 deselected。
- `python scripts/preflight.py --skip-frontend` → 离线 PASS、现场 PASS、git 体检按工作树状态如实报。
- 单条用例速查：`pytest -q -k "job_ticket or job_status or path_layer or path_entities"`
