# Holdout Set（考卷区）

> IDSD 盲考闭环的「考卷」。构建期代理不可读，评估时才由判卷机执行。

两套判卷机并存，职责不同：

| | `evaluate.py`（v1，自研） | `evaluate.ts`（idsd-harness v3） |
|---|---|---|
| 语言 | Python，场景是 `.py` | TypeScript，场景是带 front-matter 的 `.md` |
| 驱动方式 | 进程内直接调 `graphkb` 函数 | 起一个真 uvicorn，走 HTTP |
| 能做什么 | 每个切片自己的判据 | 断言 DSL + property 测试 + `--observe` + `--affected` + `--stamp` |
| 存量 | S1–S8 共 8 个切片 56 个场景 | 本目录 `scenarios/`（新写的这一批） |

**新写的考卷一律进 `.ts` 那套。** `.py` 那套保留不动——它是 S1–S8 的历史判据，
跑得通就继续跑，没必要为了统一而重写（重写等于把「当时怎么验的」抹掉）。

## 结构

```
holdout/
├── scenarios/{success,failure,boundary}/*.md   # v3 场景（front-matter 里写 checks）
├── properties/*.json                           # v3 属性测试（造输入 + 验不变式 + shrink）
├── fixtures/<name>/                            # 预置库（判卷机铺进临时 working_dir）
├── scenarios/<slice>/…                         # v1 场景（Python，历史存量）
├── results/                                    # 每轮一个版本标签，失败的轮次也存档
├── evaluate.py                                 # v1 判卷机
├── evaluate.ts                                 # v3 判卷机（来自 fjibj/fangjin-skills-factory idsd-harness）
├── runner-config.json                          # 基线门禁命令（pytest + compileall）
└── ADAPTATION.md                               # 相对上游改了哪几处、为什么
```

## 怎么跑

```bash
# 首轮：观察（新考卷必须先用这个，退出码恒 0，只记 WOULD_FAIL）
npx tsx holdout/evaluate.ts obs-$(date +%Y%m%d) --observe --skip-baseline

# 正式判分（含基线门禁：pytest + compileall）
npx tsx holdout/evaluate.ts s7-v1

# 只跑属性
npx tsx holdout/evaluate.ts prop-v1 --properties-only --skip-baseline

# 只跑某一切片
npx tsx holdout/evaluate.ts s7-v1 --slice=s7 --skip-baseline

# 按改动只跑相关（没命中任何不变式时自动回退全量）
npx tsx holdout/evaluate.ts dev-$(date +%s) --affected --skip-baseline

# 通过后打戳（把 Verified-by 行贴进 commit message）
npx tsx holdout/evaluate.ts s7-v1 --stamp
```

前置：Node 24 + `npx`（tsx 由 npx 临时拉起，仓库不装 node_modules）；
Python 侧要能被 `python` 找到，且本地 Ollama 提供 `bge-m3`。

## 夹具（`fixtures/`）

ingest 是 30 秒级的 LLM 操作，十几个场景每个都从零灌文档要跑十分钟，而场景要验的是
检索/编辑语义，不是「能不能灌进去」。所以：

- 只读/编辑类场景 → 铺 `fixtures/kb-small`（9 实体 / 12 关系 / 2 文档 / 4 块）
- 测 ingest 的场景 → 走真实上传（并标 MANUAL 或单独切片）

`kb-small` 由 `scripts/make_holdout_fixtures.py` 生成，**不需要 LLM**（只用图 + 分块 +
bge-m3 embedding），所以换机器也能一键重建。它必须与真实摄取产物同形，包括
`full_entities` / `full_relations` / `entity_chunks` / `relation_chunks` 这四张「偏本账」——
少了它们，删文档会「成功」但图上什么也不动（2026-11-21 observe 首轮就是这么红的）。

## 纪律

1. **考卷隔离**：构建期 `holdout/` 不可读（`.claudeignore` 屏蔽），场景从
   `idsd/intents/*/expectations.md` 派生，不回看实现。
2. **判卷机只读**：`evaluate.ts` 只改【适配区】；改动清单记在 `ADAPTATION.md`。
3. **每轮新版本标签**：`slice-1-v1`、`slice-1-v2`…，失败轮次也存档——它是「考题问题 vs
   实现缺陷」判别的证据链。
4. **新考卷先 `--observe`**：实战 12 轮里 8 次失败是出题问题。observe 让「先看错在哪，
   而不是先改代码」。

## 判读失败

| 现象 | 判断 | 动作 |
|---|---|---|
| 断言 200，实际 201 | 考题错 | 改断言 |
| 期望字段名不对 | 考题错 | 改字段名 |
| 期望实体数对不上夹具 | 考题错（或夹具缺表） | 先查夹具，再查实现 |
| 期望 `context_tokens ≤ 预算` 却超了 | 实现缺陷 | 记下，别急着改 |
| `502 上游不可用（HTTPStatusError）` | 环境问题（模型不可用） | 先修模型，别当缺陷 |

最后一行是 gk-visual 特有的：检索要真 LLM 做关键词抽取，模型挂了的表现是
`/api/_test/memory_search` 回 502 并带上游原因（不是 500 空 body）。
