# 接入 idsd-harness v3：做了什么、撞到什么、还剩什么

- **日期**：2026-11-21
- **依据**：《gk-visual 接入 idsd-harness v3 操作手册》§3 → §9
- **上游**：`fjibj/fangjin-skills-factory` → `idsd-harness/`（v3 合入 main，PR #1）
- **一句话**：判卷机换成了「搜反例」那一套，骨架跑通、10/13 场景绿；**检索类场景卡在
  LLM 订阅过期**，这一步要人来解。

---

## 1. 为什么不是「填两个函数」

手册 §2 说得对：`evaluate.ts` 的参考实现假设被测方是 Fastify（`app.inject` 进程内注入），
而 gk-visual 是 Python + FastAPI + LightRAG。

所以做了一层很薄的适配：`buildApp()` 返回一个**只有 `inject()` 的鸭子对象**，
底下用 `fetch` 打到真 uvicorn。判卷机的 `runCheck()` 一行没改——它不关心传输是什么。

## 2. 四块新东西

| 文件 | 作用 |
|---|---|
| `graphkb/testing.py` | 仅 `GKB_TEST_MODE=1` 注册的判卷机端点：`/api/_test/reset`、`/api/_test/memory_search`、`/api/_test/state` |
| `holdout/evaluate.ts` | v3 判卷机的适配副本（改动清单见 `holdout/ADAPTATION.md`） |
| `holdout/scenarios/*.md` | 14 个 v3 场景（12 自动 + 1 失败面 + 1 人工） |
| `holdout/properties/*.json` + `idsd/invariants.json` | 三条属性 + 六条不变式（trigger → 场景/属性） |

辅助脚本：

- `scripts/make_holdout_fixtures.py` — 生成 `holdout/fixtures/kb-small`（**不需要 LLM**）
- `scripts/verify_holdout_reset.py` — 重置隔离的现场验证（也不需要 LLM）

## 3. 三个真问题

### 3.1 reset 只清 `_shared_dicts` 不够，还有第三处

手册 §3.3 点过「只清 sqlite 会留下向量残影」。gk-visual 这边是另一个版本：

首次跑 `verify_holdout_reset.py`，第 2 步「建 A → 重置 → 查 A」挂了——

```
[2] 重置（不带夹具）
    nodes=0 edges=0
    state: nodes=0 docs=2      ← 图空了，文档还在
```

根因不在我们的代码：LightRAG 1.5.7 给 `get_namespace_data()` 加了
`_namespace_data_cache`（每进程一份字典对象引用，省掉每次拿锁）。只删 `_shared_dicts`
里的键，新实例会从**缓存**里拿回同一个旧字典对象。图之所以看起来清空，是因为图
（GraphML）根本不走共享字典。

处置：`_clear_shared_namespaces()` 同时清 `_shared_dicts` / `_init_flags` /
`_namespace_data_cache`，并补 `tests/test_rag_guard.py` 两条用例钉住。
再跑：`nodes=0 docs=0`，PASS。

### 3.2 夹具缺「偏本账」，删文档会假成功

observe 首轮 14 个场景里 5 个 WOULD_FAIL。逐条分诊后：

| 场景 | 现象 | 判断 |
|---|---|---|
| `s6-document-delete` | 删了 `doc-zhangsan`，`张三` 还在图上 | **夹具问题** |
| `s6-document-list` | 两篇文档的 `entity_count` 都是 0 | **夹具问题** |
| `s7-memory-search-*`、`f1-*` | 502 上游不可用 | **环境问题**（见 3.3） |

两个「夹具问题」同源：手搓夹具时我只写了图 + 块 + 向量，漏了
`doc_status.chunks_list` 与 `full_entities` / `full_relations` / `entity_chunks` /
`relation_chunks` 这四张表。LightRAG 删文档时**靠这四张表找该删哪些实体**，
缺了它们 `adelete_by_doc_id` 会「成功」返回、图上什么也不动；而 `entity_count` 是
按 `chunks_list` 反向算的，缺了它恒为 0。

补齐后重跑：这两个场景全绿（10/13）。

> 这就是 observe 模式的价值：这两条如果按 enforce 跑，看起来像「实现有 bug」，
> 而实际上是我出题时把夹具做薄了。

### 3.3 检索类场景卡在 LLM 订阅

`/api/_test/memory_search` 走的是真的 `MemoryTools.search` → `query()` →
`rag.aquery_data()`，**关键词抽取要真 LLM**。当前 `.env` 指的火山 CodingPlan 已经过期：

```
400 InvalidSubscription: Your account (2101867947) does not have a valid
CodingPlan subscription, or your subscription has expired.
```

处置：测试端点把上游异常转成 **502 + 原因**（而不是 500 空 body），这样判卷机输出
直接写着「上游不可用」，一眼能分出「环境问题 / 出题问题 / 实现缺陷」。

`python -X utf8` 直连 LLM 的探针同样 400，所以不是 gk-visual 的问题。

## 4. 当前实测结果

`npx tsx holdout/evaluate.ts obs-20261121b --observe --skip-baseline --no-properties`

```
Total scenarios: 14
Passed:          10 ✅
Would fail:      3 ⚠️   （全部是 502 上游不可用）
Manual:          1 ⏭️
Pass rate:       76.9%
```

通过的 10 条覆盖：空库读图、读图带溯源、改实体、合并实体、建关系、文档列表统计、
删文档收敛、改/删不存在的对象返 404、空白文档拒收。

其它已验证：

- `scripts/verify_holdout_reset.py` → PASS（建 A → 重置 → 查 A 为空；重铺可重新加载）
- `--affected` → 改 `graphkb/rag.py` 命中 INV-04/INV-05，只跑 s4/s6 那几条
- `--stamp`、`properties` 待 LLM 恢复后一起验

## 5. 还没做的

- **三条 property 没跑过**（都要 LLM）。`PROP-02` 依赖手册 §6.3 那行 `substitute` 修复，
  已经改进了 `matchOp()`，但没实测过 `{{budget}}` 真的替换成功。
- **`--stamp` 没跑过**：它的前提是零失败，现在还有 3 条红的。
- **fixture 扩展已加**（`parseScenario` / 主循环 / `runPropertyOnce`），但只在场景路径上
  用过一次（`kb-small`），property 路径没验。
- **`entity_chunks` / `relation_chunks` 的 key 形状**是照上游 `make_relation_chunk_key`
  （`<SEP>` 连接、名字排序）写的，删文档那条场景绿了说明至少这条链路是对的；
  但「共享实体在两个文档里都出现时删一个」这种情形没考。

## 6. 怎么接着跑

```powershell
# 1) 模型恢复后先看检索类场景
npx --yes tsx holdout/evaluate.ts obs-20261122 --observe --skip-baseline

# 2) 三个都绿了再切 enforce（含基线门禁）
npx --yes tsx holdout/evaluate.ts v3-v1 --stamp

# 3) 把戳贴进 commit message
```

判定标准（手册 §9）：observe 能说清每个 WOULD_FAIL 的性质 / enforce 下 ≥ 8 个场景
通过率 ≥ 90% / 至少一条 property 真的抓到过问题（或负向验证确认有效）/ reset 隔离通过 /
`--affected` 命中正确 / `--stamp` 产出替换行。
