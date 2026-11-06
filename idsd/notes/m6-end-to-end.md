# M6 记录：端到端闭环（写侧串行化 + 单机 demo）

> 日期：2026-11-06
> 范围：`graphkb/documents.py`（写侧串行化）、`tests/test_documents.py`（并发用例）、`scripts/demo_agent_memory.py`（新）
> 上游：M2 的 `memory.search/ingest`、M3 Inline&Spill、M4 溯源、M5 触发器
> 闭环要回答的问题：**「干活 → 存记忆 → 下次真想起来」这条线，一次跑通没有？**

## 1. 为什么最后才补写侧串行化

M2–M5 都在读侧（检索、注入、溯源、触发）。写侧一直只有 S6 的 `upsert_document`，
它的覆盖更新是「先 `adelete_by_doc_id(旧)` 再 `ainsert(新)`」——两步之间没有任何互斥。

M2 之后 `memory.ingest` 把它暴露给了 agent：**同一库上两个 agent 同时写，是会发生真交错的**。
交错长这样（`_SlowRag` 每次写让出一次事件循环，把 timsort 式的窗口掰开）：

```
delete 笔记A → delete 笔记B → insert[笔记A] → insert[笔记B]
```

A 刚删掉、B 也删掉，然后两边一起插。图收敛（entity/relation 的 `<SEP>` 属性并集）在同一份
GraphML 上被两个协程同时改，等于把 M4 好不容易读准的 `source_id` 搅乱。这不是理论问题：
只要 harness 里有两个子 agent 各写各的笔记，它就会发生。

## 2. 实现：按「运行中的事件循环 + 工作目录」分桶的模块级锁

```python
_WRITE_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}

def _write_lock(rag) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), str(rag.working_dir))
    return _WRITE_LOCKS.setdefault(key, asyncio.Lock())
```

三个决定：

1. **锁在模块级，不在 rag 对象上**——rag 对象每次 `init_rag` 都是新的，挂在它身上等于没锁。
2. **key 带 `id(运行中的事件循环)`**——CLI 每次 `asyncio.run` 都是一个新循环，
   上一轮循环里的 `asyncio.Lock` 在新循环里用会炸（绑定 loop 的实现）。带上 loop id，换循环就是新锁。
3. **key 带 `working_dir`**——不同 workspace 的写本来就互不影响，锁范围压到最小，
   免得一个拖拉的库把另一个库的写卡住。

`upsert_document` 的「先删后插」整段包进 `async with _write_lock(rag):`。

**没做分布式锁**：单机单进程是当前唯一的部署形态（约束 5「先地基后天花板」）。
多进程/多机写同一 workspace 要真文件锁，那是另一码事，写进 §6 边界。

## 3. 反证：先让用例红过一遍

并发用例最容易写成「恒真」——上一版 `test_concurrent_delete_and_upsert_are_serialized`
的两个分支写得一模一样，断言永远成立，等于没有测试。

这次的 `test_concurrent_upserts_do_not_interleave` 用 `_pairs(calls)` 把调用序列切成
`(delete, insert)` 对，要求恰好是 `[(笔记A,笔记A), (笔记B,笔记B)]`。**把锁临时换成 `if True:`
立刻红**：

```
AssertionError: [('delete','笔记A'),('delete','笔记B'),('insert',['笔记A']),('insert',['笔记B'])]
```

恢复后 5 passed。用例能抓交错，才叫用例。

## 4. demo：一条命令跑完读侧

`scripts/demo_agent_memory.py` 不是测试，是**账本**——每步打印触发事件、扫到几个实体、
花了多少 token、总闸还剩几格。

读侧（`--workspace data`，`data/` 那 17 个实体的小图，全离线不花 LLM）：

```
探针载入实体名 17 个

  ① 起手 H1   锚='张三 北京'   实到=2  查了        token=247/800  总闸余=4
  ② 埋坑 H2   锚='张三'        实到=1  查了        token=119/800  总闸余=3
  ③ 回想 H3   锚='张三'        实到=1  查了        token=119/800  总闸余=2
  ④ 离题 H3   锚='今天天气不错…' 实到=0  没查(no_entity)   —       总闸余=2
  ⑤ 点名 H0   锚='张三'        实到=1  查了（豁免）  token=119/800  总闸余=2
  ⑥ 总闸耗尽  锚='张三'        实到=1  没查(gate_exhausted) —     总闸余=0
  ⑦ 被拦后点名 H0  锚='张三'    实到=1  查了（豁免）  token=119/800  总闸余=0
```

这一张表本身就是 M2–M5 的验收：H1/H2/H3 都真查到了（`hit=true`）、
离题句探不到实体就一格不扣、总闸耗尽后自动钩子被拦而 H0 照样能查。
每次的 `answer_context` 只有 119–247 token，因为无关块在 M3 的修复里已被挡在注入之外。

## 5. 写侧闭环：写进去的，下次真能想起来

`--ingest` 用临时 workspace（不污染 `data/`），真 LLM 真抽取：

```
探针载入实体名 0 个                       ← 空库，探针空着是对的
[写] memory.ingest(source=session) …… 一次抽取大约几十秒
     status=done doc_id=直播复盘-20261106 entities=7 relations=6
     图变了，探针重载：7 个实体名
  ① 起手 H1   锚='张三 入职材料 北京 社保'  实到=4  查了  token=377/800  总闸余=4
  ...
  ⑧ 写后 H0   锚='张三 入职材料'            实到=2  查了  token=159/800  总闸余=0
  —— 注入里有没有刚学到的内容： 有
```

两句话的复盘（「张三这周把入职材料补齐了，社保由北京那边的 HR 对接。另外确认了字节跳动的
办公地点就在北京，通勤大约 40 分钟。」）抽出 **7 实体 / 6 关系**，
写完后 H0 一次就问回来了，注入 159 token 里包含刚学到的「社保」。

**关键一环是写后的 `probe.refresh(rag)`**：探针是会话启动时载入的实体名快照，
不重载就永远看不见新实体——第一次跑 demo 时正是漏了这一步（写前空库、写后仍 0），
表现出来是「刚写完就忘了」。这条不是 demo 的细节，是 harness 必须记住的一条：
**写侧成功后要重载探针**，否则新记忆对自动钩子不可见（H0 不受影响，它不靠探针）。

## 6. 换真图跑一遍（探针 B 那 260 个实体）

小图（`data/`，17 实体）只能证明「机制对」，证明不了「真库能不能用」。
把探针 B 灌的那张真图（`C:\Users\fjibj\cola\outputs\gk-probe\probe-data`，
260 实体 / 371 关系 / 24 个连通分量）拷一份出来跑，才是压边界：

```bash
python scripts/demo_agent_memory.py --workspace <复制的库> --preset real
```

结果（同一个 demo，只换库和演示文本）：

| | 小图 17 实体 | 真图 260 实体 |
| --- | --- | --- |
| 探针载入 | 17 个名字 | 260 个名字 |
| H1 探到实体 | 2 | 4（触发器 / 无感记忆 / memory.search / harness） |
| 注入 token | 247 / 800 | **797 / 800** |
| inline 条数 | 5 | 9 |
| spill | 0 | **41 条 / 4380 token** |
| 离题句 | 探不到，不查 | 探不到，不查 |

**真图上立刻暴露一个缺陷**：注入里出现 `[path] MVP` 这种**裸名字段**。
原因是 `_hit_trace` 给命中项拼属性时只从「向量召回的上下文」里找同名实体，
而路径中间节点（多跳里被串起来的那种）往往不在召回集里 → 类型和描述全是 `None`。
小图上路径都是直连（一跳到头），没有中间节点，所以一直没露。

已修：`_hit_trace` 顺带读一次全图节点，按名字补 `type` / `description`
（向量召回那份若更全则以它为准）。反证做过：把回图取的那行改成 `attrs = {}`，
新用例立刻红（`assert None == 'event'`）。修完同一句 H1 变成 
`[path] MVP（event）：最小可行产品阶段……`。

**剩下的问题（策略层，未改）**：800 token 在真图上只装得下 9 条，41 条溢出。
根因不是预算小，而是**密度低**——每条描述是 LightRAG 把多份文档里的同类陈述用 `<SEP>`
拼起来的近重复句（如 `memory.search` 一段 161 token，里面三段都在说「入参 context 和 budget」）。
可选方向：拼句去重、按段截断而不是按总长截断、或把 800 按层分配（anchor 占大头、path 只留一句）。
这属于注入策略，不是 bug，没动。

## 7. 真图回归：不再手动拷数据跑

上一节是手动跑的（拷库 → 改 demo 文本 → 看输出）。手动跑一次只能发现一次问题，
所以固化成两道用例（`tests/test_real_graph.py`）：

**回放组（CI 跑）** —— 夹具进内存，零网络、零 LLM：

| 用例 | 钉住什么 |
| --- | --- |
| `test_fixture_is_sanitized_and_real_shaped` | 夹具要像真图（≥ 50 节点、描述非空、带点号名字）且已脱敏 |
| `test_fixture_descriptions_keep_sep_structure` | `<SEP>` 拼接的长描述必须留着（密度问题从这里来） |
| `test_layers_on_real_graph` | 分层不跑到图外；关系两端都在命中集；层只有三态 |
| `test_paths_are_consistent` | 中间节点必须是 path（锚点/引用点自己优先）；真图上确实存在中间节点 |
| `test_no_entity_lost_attributes_on_real_graph` | 这次那个 bug：中间节点必须从图上拿到 type / description |
| `test_replay_is_deterministic` | 同一夹具两次回放结果一致 |
| `test_injection_lines_are_never_bare_names` | 注入里每行都带类型 + 描述 |
| `test_injection_respects_budget_and_accounts_every_item` | 预算硬上限；装不下的进 spill，引用不重复、前缀合法 |
| `test_injection_on_real_graph_saturates_realistically` | 800 token 在真图上装不完这个事实（防止夹具退化成小图） |
| `test_probe_loads_real_scale_names` / `..._ignores_off_topic_text` | 80 个名字同时挂在探针上；离题句 0 命中 |
| `test_single_anchor_does_not_fabricate_paths` | 单锚点连不出路径时不许拿邻居充数 |

**M1–M5 逐层真图用例**（2026-11-06 补，夹具多了 `text_chunks.json` 之后才可能）：

| 层 | 用例 | 钉住什么 |
| --- | --- | --- |
| M1 | `test_m1_anchor_and_evidence_are_separated` | 同一检索、换文本就换分层：锚点只来自 `anchor_text`、证据只来自 `evidence_text`，引用点要么有路径要么进 `disconnected` |
| M1 | `test_m1_human_face_takes_evidence_from_answer` | 人类面行为不变：证据位取那次生成的答案 |
| M1 | `test_m1_equal_texts_rejected_on_real_graph` / `..._agent_face_never_generates_answer` / `..._missing_evidence_rejected` | 两参相等必抛；Agent 面一次 LLM 答案都不花 |
| M2 | `test_m2_search_shape_on_real_graph` | 四个返回块（`answer_context` / `spill_refs` / `hits` / `trace`）都不缺席；命中项带 `origin` + `provenance` |
| M2 | `test_m2_texts_equal_degrades_on_real_graph` | query 缺省 → 如实降级成 `human` + `reason=texts_equal`，不唏着骗 |
| M2 | `test_m2_unlinked_chunks_stay_out_of_injection` | 真图上必然有「话题相似但实体无关」的块：留在 `hits` 里标 `linked=false`，不进注入也不进溢出清单 |
| M2 | `test_m2_real_graph_injection_is_dominated_by_path_nodes` | 真图注入里 `[path]` 过半（1 锚 + 2 引用 → 10 行 path）——密度问题的根因，铉在这里 |
| M2 | `test_m2_real_graph_overflow_lands_on_chunks` / `..._budget_truncated_is_overflow_not_drop` | 实体/关系刚好装下时，溢出全落在块上；记账要平 |
| M2 | `test_m2_no_anchor_falls_back_honestly` | 离题文本：`vector_fallback` 或 `no_anchor` 两种都要说出来 |
| M3 | `test_m3_spill_then_expand_roundtrip` | 溢出的引用能无状态取回（真图上全部命中）；`expand` 也带溯源 |
| M3 | `test_m3_expand_reports_missing_with_reasons` / `..._truncates_and_caps` | 四类取不到都给原因；`max_tokens` 截断带 `…`；一次最多 20 条 |
| M4 | `test_m4_real_nodes_are_extracted_and_resolve_docs` | 真图 80 节点全为 `extracted`、`unresolved=0`、来源文档 ≥ 2 篇 |
| M4 | `test_m4_manual_and_mixed_marks_on_real_copy` | 在真图副本上打 1.5.6 / 1.5.7 两种手工痕迹 + 一条混合，分别得 `manual` / `manual` / `mixed` |
| M4 | `test_m4_search_and_expand_carry_provenance` | 检索与取回两边的溯源不会各说一套 |
| M5 | `test_m5_h1_on_real_names` / `..._h2_and_h3_on_real_names` | 80 个名字挂探针上：H1 探到两个锚、H2 从报错里探到实体、H3 从上下文里探到 |
| M5 | `test_m5_offtopic_skips_and_gate_holds_on_real_graph` | 离题句 `no_entity` 不扣格；手动耗尽总闸后 `gate_exhausted`；H0 照样能查且 `exempt=True` |

**现场组（本地跑，CI skip）** —— `test_live_real_workspace_end_to_end`：
它在用例里自己把真库拷进 `tmp_path`（不碰原件），然后跑探针 → H1 → 离题 H3 → H0，
再手动跑一次 `memory.search`（小预算强制溢出）→ `memory.expand`（实体/关系/块都取一遍）→ 全图溯源。
断言：探针 ≥ 200 个名字、H1 命中且注入无裸名字、离题句不查、H0 豁免总闸、
溢出的引用全部取得回、260 个节点全为 `extracted` 且 `unresolved=0`。
需要真库 + 本地 Ollama，两者缺一就 skip；`-m "not slow"` 也可以主动跳过。

注意现场组把数据拷进 `<tmp>/ws/live/` 并设 `workspace="live"`——不是为了好看：
LightRAG 的 KV 挂在进程级共享字典上（见下面 §10），不隔离的话跑完整套用例时
块存储会是空的（图还能读，所以现象很诱人：图文对得上，块全 `missing`）。

**夹具为什么脱敏**：夹具要进公开仓库，而真图里的描述是从我的设计文档抽出来的句子
（含项目名、路线代号）。`scripts/capture_real_fixture.py` 默认把实体名与文本换成等长填充，
只保留结构——节点数、度数、`<SEP>` 分段数与每段长度、带点号的方法名——
token 估算因此仍然可复算。要留原始副本用 `--raw`，但别提交。
录制时脚本自己拷一份临时库，不动原件。

## 8. 边界

- **单进程**：锁只在进程内有效。多进程/多机写同一 workspace 需要文件锁，未做。
- **锁粒度是整个 upsert**：不同文档的覆盖更新也排队。个人库写入频率低，排队的代价远小于交错的代价；
  真成瓶颈再按 doc_id 分桶。
- **探针重载是调用方的责任**：`memory.ingest` 自己不知道 harness 手里握着探针。
  `ingest` 的返回里有 `entities`，harness 可以增量 `probe.replace(...)`，也可以整体 `refresh`。
- **demo 依赖真库内容**：①–⑦ 的 token 数字取决于 `data/` 里有什么，换库就不再一样。

## 9. 测试

- `tests/test_documents.py` 6 → 5 passed（删掉恒真的旧用例，加 `test_concurrent_upserts_do_not_interleave`）。
- `tests/test_render.py` 新增 `test_hit_trace_path_node_attrs_come_from_graph`（真图那个裸名字缺陷的回归）。
- `tests/test_real_graph.py`：13 条链路回放 + **21 条 M1–M5 逐层回放** + 1 条现场用例。
- `tests/test_rag_guard.py` 新增 3 条（同 workspace 冲突要 warning）。
- 全量：**190 passed**（含现场用例，本机真库 260 实体 + Ollama）；CI 里现场用例 skip，报 189 passed / 1 skipped。

## 10. 真图跑 M1–M5 发现的两件事（2026-11-06）

小图（4~5 个节点、9 条注入）上这两件事都看不见，换了 260 实体的真图才露头：

**① 注入的主体是路径中间节点**。`query=一个锚点`、`task` 点名两个实体时，命中 7 实体 / 6 关系，
13 行注入刚好塞满 668 token——其中 `[path]` 占 10 行。三个锚点、无引用点更极端：12 行里 9 行 path，
同时 4 条关系 + 8 块溢出 3296 token。中间节点只需要证明「这两个人连得上」，却和锚点抢同一份额度；
块（chunk）基本进不了注入，所以 `reason=budget_truncated` 在真图上是**常态**，`degraded` 在那儿失去区分度。
三条候选（拼接句去重 / 分段截断 / 按层分配预算）已入 [`backlog.md`](../backlog.md) 条目 18，
建议先做「按层分配预算」：path 只留名字 + 类型，描述需要时用 `entity:` 取回——不丢信息。

**② 同进程里两个实例、同 workspace，KV 存储静静地空**。现象：跑完整套 pytest 时，
现场用例的 `memory.expand` 对所有 `chunk:` 引用报「块存储里没有这个 chunk」，
而同一时刻图能读到 260 个节点。单独跑 `tests/test_real_graph.py` 却全绿——只跟用例顺序有关的东西，
八成不是我们的 bug 而是别人的状态。

根因：LightRAG 把 KV 数据挂在**进程级**共享字典 `_shared_dicts[workspace:namespace]` 上，
「谁负责从磁盘加载」只是个全局初始化标志；先建的实例（`workspace=""`）把 `:text_chunks` 标成已加载并填了它那份，
后指向真库的实例看到标志就不再读自己的 JSON → 块 0 条。独立探针复现：实例 A（空库）→ 实例 B（真库副本）
→ B 的 `text_chunks` 0 条、按 id 取块 `None`；换唯一 `workspace` 后一切正常。GraphML 不受影响
（每个实例自己读文件），这就是「图文对得上、块全没了」这副诡异现象的来源。

处置：`graphkb/rag.py` 加 `_warn_if_workspace_shared()`——同 workspace、不同 `working_dir` 时 warning，
把坑喊出来而不偷偷绕过；现场用例改用 `<tmp>/ws/live/` + `workspace="live"` 做隔离；
根治方案（自动隔离 / 报上游 / 定死单库单进程）入 [`backlog.md`](../backlog.md) 条目 19。

## 11. 处置（2026-11-06 当天做完）

**① 注入密度 → 按层分配预算**（`graphkb/memory_api.py: LAYER_SHARES`）。
anchor 40% / cited 25% / direct 15% / path 12% / chunk 8%；path 层只带名字 + 类型（描述靠 `entity:` 取）；
份额是**软上限**（后面几层花不完的额度当前层可以先吃，否则「预算恰好够用」会被错杀），
用不完的往下传，每层花费记进 `budget_used.context_by_layer`。

同图同 800 token 的实测：

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| 1 锚 + 2 引用 | inline 13 / 668 token，spill 3 块 / 1146 | inline 14 / 692，spill 2 / 764 |
| 3 锚无引用 | inline 12 / 794，spill 12 / 3296 | inline 17 / 735，spill 7 / 2674 |
| demo 真图 H1 | inline 9 / 797，spill 41 / 4380 | inline 34 / 734，spill 16 / 2936 |

**② 同进程同 workspace 的 KV 串台 → 自动隔离**（`graphkb/rag.py: _isolate_shared_kv`）。
判定不看「谁先谁后」而看**内容**：我的磁盘文件里有、共享字典里没有 → 把这个存储换成
本实例自己的字典（读自己的文件、写也只落自己的目录）；同库重复建实例则不动，保持上游共享语义。
现场组已改回 `workspace=""`，靠它自动隔离跑通（日志实测 8 个 KV 存储被脱钩）。

代价：被隔离的实例不再与其它实例共享内存（本来指向不同目录，共享才是错的）；
多进程 `initialize_share_data` 那套协议没参与（graphkb 目前单进程）。这仍是 graphkb 层的补丁，
上游该把「库目录」也纳入初始化判定——留给报 issue。