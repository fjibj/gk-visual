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

## 5. 换真图跑一遍（探针 B 那 260 个实体）

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

## 6. 边界

- **单进程**：锁只在进程内有效。多进程/多机写同一 workspace 需要文件锁，未做。
- **锁粒度是整个 upsert**：不同文档的覆盖更新也排队。个人库写入频率低，排队的代价远小于交错的代价；
  真成瓶颈再按 doc_id 分桶。
- **探针重载是调用方的责任**：`memory.ingest` 自己不知道 harness 手里握着探针。
  `ingest` 的返回里有 `entities`，harness 可以增量 `probe.replace(...)`，也可以整体 `refresh`。
- **demo 依赖真库内容**：①–⑦ 的 token 数字取决于 `data/` 里有什么，换库就不再一样。

## 8. 测试

- `tests/test_documents.py` 6 → 5 passed（删掉恒真的旧用例，加 `test_concurrent_upserts_do_not_interleave`）。
- `tests/test_render.py` 新增 `test_hit_trace_path_node_attrs_come_from_graph`（真图那个裸名字缺陷的回归）。
- 全量 `pytest -q`：**149 passed**（本机 lightrag 1.5.7，与 CI 同版）。
