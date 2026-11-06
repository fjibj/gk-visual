# gk-visual（Python 包名 `graphkb`）

透明、可手工编辑的个人知识库：把文档抽成图谱，**检索过程看得见**，**图人也能改**。

> 仓库名 `gk-visual`，代码里的包名/CLI 名保持 `graphkb`（不改导入路径）。持续更新中，进度与已决事项见 §8。

[![CI](https://github.com/fjibj/gk-visual/actions/workflows/ci.yml/badge.svg)](https://github.com/fjibj/gk-visual/actions/workflows/ci.yml)

两条主张决定了这套代码的形状：

- **透明**：每次检索都吐出结构化 `trace`（捞到什么、凭什么判定命中、哪些没被用上）。前端图上的高亮就是这个 trace 的直接投影，不是事后美化。
- **可编辑**：图是活数据库，不是原文派生的只读物。手工加的节点/关系，下一次检索就会尊重它。

---

## 1. 环境要求

| 需要 | 说明 |
| --- | --- |
| Python ≥ 3.10 | 后端 + CLI + 测试（实测 3.12.10） |
| 一个 LLM | Anthropic 兼容 / OpenAI 兼容 / Ollama，三选一，见 §3 |
| 一个 embedding 服务 | 默认走本地 Ollama `bge-m3`（`localhost:11434`） |
| Node ≥ 18 | **仅构建前端时需要**；运行时不需要 Node |

图引擎复用 [LightRAG](https://github.com/HKUDS/LightRAG)（进程内 `import lightrag`），本项目不自己写图数据库、不自己写检索。

## 2. 安装

```bash
git clone https://github.com/fjibj/gk-visual.git && cd gk-visual
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .                                  # 核心 + server + 文件解析依赖
pip install -e ".[dev]"                            # 加 pytest
pip install -e ".[dev,mcp]"                        # 再加 Agent 记忆面（MCP，stdio）
```

依赖里写的是 `lightrag-hku[api]`：本项目 `server.py` 需要 fastapi/uvicorn，而文件解析要用的 `pypdf / python-docx / python-pptx / openpyxl` 是 LightRAG 解析层的按需依赖（缺一个少一种格式，所以四个都显式列了）。`python-multipart` 也在——FastAPI 的文件上传（`UploadFile`）没它就直接报错。

## 3. 配置

```bash
cp .env.example .env      # .env 已被 .gitignore 排除，密钥不会入库
```

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| `GKB_LLM_PROVIDER` | `anthropic` | `anthropic` \| `openai_compat` \| `ollama` \| `mock` |
| `GKB_LLM_MODEL` | `deepseek-v4-flash` | 模型名 |
| `GKB_LLM_BASE_URL` | 空 | 自建/中转端点（如火山 Coding Plan） |
| `GKB_LLM_API_KEY` | 空 | 密钥，只进本地 `.env` |
| `GKB_LLM_MAX_TOKENS` | `8192` | — |
| `GKB_LLM_DISABLE_THINKING` | `false` | 关掉推理段（部分模型需要） |
| `GKB_EMBEDDING_PROVIDER` | `ollama` | `ollama` \| `openai_compat` \| `mock` |
| `GKB_EMBEDDING_MODEL` | `bge-m3` | — |
| `GKB_EMBEDDING_BASE_URL` | `http://localhost:11434` | — |
| `GKB_EMBEDDING_DIM` | `1024` | **必须与模型实际维度一致**，改了要重建库 |
| `GKB_EMBEDDING_MAX_TOKEN_SIZE` | `8192` | — |
| `GKB_WORKING_DIR` | `./data` | 库目录（图 + 向量 + 文档），已 gitignore |
| `GKB_LANGUAGE` | `Chinese` | 抽取时的工作语言 |
| `GKB_WORKSPACE` | 空 | 多库隔离用；同进程跑多实例时**必须**各设一个（见 `idsd/backlog.md` 条目 6） |
| `GKB_HIT_TOP_K` | `5` | 向量召回规模：只用于兜底锚点与给候选打分 |
| `GKB_MAX_HOPS` | `4` | 锚点↔答案引用点最多连几跳，连不上就报「无路径」 |
| `GKB_MAX_PATHS` | `6` | 等长最短路最多展示几条（有歧义时宁可全显示） |
| `GKB_MAX_UPLOAD_MB` | `50` | 文件上传大小上限（S8） |

后三个是「防爆炸上限」，不是调优旋钮：改它们不改变命中判据本身（锚点 / 答案引用 / 最短路），只改变允许多宽。判据的来历与五轮演进见 [`idsd/notes/retrieval-hit-and-highlight-encoding-log.md`](<idsd/notes/retrieval-hit-and-highlight-encoding-log.md>)。

## 4. 跑起来

```bash
python -m graphkb.cli doctor          # 自检：LLM / embedding / LightRAG 三件是否都通
python -m graphkb.cli serve           # Web UI -> http://127.0.0.1:8000
```

`serve` 托管 `frontend/dist`。**第一次（或改过前端）要先构建**：

```bash
cd frontend && npm install && npm run build && cd ..
```

改前端时可以用开发模式热更新（vite 在 :5173，`/api` 代理到 :8000）：

```bash
cd frontend && npm run dev
```

UI 里能做的：上传/覆盖更新/删除文档（支持文件 docx/xlsx/pptx/pdf/txt/md 与粘贴文本）、看图、改点改边、合并实体、检索并在图上看命中分层（实线环=锚点、虚线环=答案引用、更细的虚线=路径中间点；色温分轮次，角标 ¹²³ 标第几轮）。

## 5. CLI

```bash
python -m graphkb.cli ingest samples/sample1.txt          # 文档 -> 图
python -m graphkb.cli query "张三在哪工作"                  # 检索 + 打印透明窗
python -m graphkb.cli query "张三在哪工作" --json           # 原始 trace JSON
python -m graphkb.cli merge 张一一 --into 张三              # 显式实体对齐
python -m graphkb.cli doctor                                # 配置与连通性自检
python -m graphkb.cli serve --port 8001 --reload            # 换端口 / 后端热重载
python -m graphkb.cli trigger plan "帮我整理张三的入职材料"    # 抬一次记忆钩子（见 §11）
```

装好包后同样的命令可写作 `graphkb query ...`。

## 6. 验证

```bash
python -m pytest -q                                   # 单元 + 真图回归（当前 187 passed，全程离线，LLM/embedding 走 mock）
python -m pytest -q -m "not slow"                      # 跳过需要真库 + Ollama 的现场用例（CI 里自动 skip）
python holdout/evaluate.py slice-7-retrieval-visualization --version slice-7-v1
python holdout/evaluate.py slice-8-document-ingestion-enhancement --version slice-8-v1
```

**真图回归**（`tests/test_real_graph.py`）：不只拿 4~5 个节点的玩具图测，而是用一张真图夹具把 **M1–M5 逐层压一遍**——
双文本判据（M1）、`memory.search` 的面与降级（M2）、Inline & Spill → `memory.expand` 闭环（M3）、
溯源四态与块→文档反查（M4）、四钩子 + 总闸（M5）。
夹具在 `tests/fixtures/realgraph/`，由 `scripts/capture_real_fixture.py` 从真库录一份：
`graphml` + `aquery_data` / `entities_vdb` 的原样返回 + `text_chunks`（图上 `source_id` 引用的那几块原文）。
默认**脱敏**——只保留结构（节点数、度数、`<SEP>` 分段与长度、带点号的方法名），文字换成等长填充，因为仓库是公开的。
只想补块、不想重跑检索引擎时加 `--chunks-only`（纯读，零 LLM）。
另外一条 `slow` 用例会在本地自动拷一份真库跑 H1 / 离题 H3 / H0 + `search`→`expand` + 全图溯源，**不用手动搬数据**；CI 里没那张图，自动 skip。

holdout 是 IDSD 的「考卷区」：场景由 `expectations.md` 派生、不回看实现，构建期对代理不可见（见 `holdout/README.md` 与 `.claudeignore`）。判卷结果存档在 `holdout/results/<版本>/report.json`。

## 7. 代码地图

```
graphkb/
  config.py      # env -> Config（含 RetrievalConfig）
  rag.py         # 按配置构建并初始化 LightRAG 实例（顺手喊出「同进程同 workspace」的坑）
  providers/     # llm/embedding 适配：anthropic | openai_compat | ollama | mock
  ingest.py      # 文档 -> 图（增量、实体对齐）
  documents.py   # 文档生命周期：列表 / 覆盖更新 / 删除后图收敛
  merge.py       # 显式合并实体（复用 LightRAG amerge_entities）
  provenance.py  # 溯源标签：origin（extracted/manual/mixed/unknown）+ 来源文档（从 source_id / chunk 存储读出来）
  query.py       # 检索 + 命中分层（锚点 / 答案引用 / 最短路）-> trace
  render.py      # 把 trace 渲染成 CLI 可读的透明窗
  server.py      # FastAPI：/api/graph /api/query /api/documents /api/entities ... + 静态托管
  memory_api.py  # Agent 记忆面逻辑：search / expand / ingest / ingest_status + Inline&Spill（不 import mcp，可离线测）
  mcp_server.py  # MCP 适配器（stdio）：把 memory_api 挂成工具；日志走 stderr，stdout 只过 JSON-RPC
  triggers.py    # M5 触发器：三钩子 + H0 兜底 + 会话总闸 + 实体探针（不 import mcp，可离线测）
frontend/
  src/main.ts    # Cytoscape 图 + 检索高亮 + 编辑面板（无框架，原生 TS）
  src/api.ts     # 后端契约类型
tests/           # pytest，LLM/embedding 走 mock，不联网
holdout/         # 考卷（见 §6）
idsd/            # 方法论记录：intents / plans / checkpoints / notes / backlog
data/            # 库本体（gitignore）
```

## 8. 约束与决策记录

- 总意图与硬约束：[`idsd/intents/overall/intent.md`](<idsd/intents/overall/intent.md>)（其中约束 1 锁死「图引擎复用 LightRAG」，所以本项目是 Python-only 后端；约束 6 是「规则预算 ≤ 1」，能靠结构判据解决的就不加关键词规则）。
- 每个切片为什么做成这样：`idsd/checkpoints/`。
- 当下明确不做的事（含理由）：[`idsd/backlog.md`](<idsd/backlog.md>)。
- 进度：[`idsd/idsd-status.yaml`](<idsd/idsd-status.yaml>)（切片维度：S1–S7 验收收官；S8「文档摄取增强」已实现并跑通 pytest 与 holdout，浏览器端的人工验收待做）。
- 个人底座阶段（M0–M6，2026-11）的完成情况见 §13；过程记录在 `idsd/notes/m3-inline-spill.md`、`m4-provenance.md`、`m5-triggers.md`、`m6-end-to-end.md`。

## 9. 已知边界（诚实的局限）

- **高亮跟着答案措辞走**：命中判据里的「答案引用」来自 LLM 答案文本，答案若只用代词或换一种说法，对应实体可能不进红圈——兜底是答案面板里的「捞到未用」列表，它保证召回可见，但不替你判定。
- **孤立实体不被召回**：图里没有连边的实体不会进入检索结果（LightRAG dual-level 检索的固有行为，见 [`idsd/backlog.md`](<idsd/backlog.md>) 条目 4）。
- **图长大后「簇」信号会退化**：现在靠「锚点 + 答案引用 + 最短路」定高亮；若图长成单个大连通分量，簇数就失去区分意义，只剩前两者有效。
- **前端色温/形态档位写死**：`frontend/src/main.ts` 里的轮次配色与环形态是常量，没做成配置项（跨 TS/Python 边界，收益低，明确后置）。
- **溯源只到「有没有人碰过」**：`origin` 能分出抽取 / 人工 / 混合，但分不出「谁在什么时候改的」；也没有“抽取后又被人改回去了”这种历史（要真审计日志，不在个人底座阶段）。
- **URL 抓取未做**：S8 只做了本地文件解析；网页抓取涉及 SSRF/超时/正文抽取，需单独切片。
- **没有鉴权**：`serve` 只该绑 `127.0.0.1`，别指望它挡人。CI 只覆盖 pytest 与前端构建（`.github/workflows/ci.yml`），**不覆盖 holdout**——那要跑真模型，成本与稳定性都不适合放 CI。
- **同进程里别开两个同 workspace 的库**：LightRAG 的 KV 存储挂在进程级共享字典（`_shared_dicts[workspace:namespace]`）上，"谁负责从磁盘加载"只是个全局标志。后果是第二个实例的 `text_chunks` / `full_docs` 会静静地为空（图还能读，因为 GraphML 是每实例自己读文件）——不报错，只是块全查不到。`graphkb/rag.py` 遇到这种冲突会 warning；要并行多个库就给不同 `workspace`（文件在 `<working_dir>/<workspace>/` 下）或拆进程。
- **注入预算在真图上是瓶颈**：260 实体的真图上，一段话的命中往往就有 10~13 行注入，其中过半是 `[path]` 中间节点（`1 锚 + 2 引用点` → 10 行 path）。块（chunk）基本装不进 800 token，常以 `reason=budget_truncated` 溢出——那是溢出不是丢弃（引用都在 `spill_refs`），但也意味着 `degraded` 在真图上是常态，别当异常告警读。怎么压：见 [`idsd/backlog.md`](<idsd/backlog.md>) 条目 18。

## 10. Agent 记忆面（MCP，已实现）

同一个 core，两个面：`server.py`（HTTP，人用）与 `mcp_server.py`（stdio，Agent 用）。MCP 这面把四个工具挂出来：

| 工具 | 用途 |
| --- | --- |
| `memory.search` | 检索：锚点取 `context.query`、证据取 `context.task`，回 `answer_context`（唯一建议注入的）+ `spill_refs`（溢出可取回）+ `hits`/`trace`（只供审计）+ `degraded`/`reason` || `memory.expand` | 把 `spill_refs` 里的引用取回原文（`entity:张三` / `relation:A->B` / `chunk:c1`） || `memory.ingest` | 写入：默认异步，回 `job_id`（一次抽取约 28s，不能堵住 agent） |
| `memory.ingest_status` | 查写入进度（`queued\|running\|done\|error\|unknown`） |

启动（scope 在启动时绑定，工具参数里没有团队/群/域）：

```bash
pip install -e ".[mcp]"
graphkb-mcp --workspace ws-personal          # 或 --workspace ws-team-fangjin
```

客户端配置示例（Claude Desktop / Cola 这类 stdio 客户端）：

```json
{
  "mcpServers": {
    "gk-visual": {
      "command": "graphkb-mcp",
      "args": ["--workspace", "ws-personal"]
    }
  }
}
```

几条设计上的硬规定：

- **`answer_context` 与 `trace` 分家**：前者预算内、可以注入 agent 上下文；后者完整、只给人看。看得见 ≠ 塞进去（防“把所有 observation 都糊进 prompt”那种死法）。
- **Inline & Spill**：预算内进 `answer_context`；装不下的**不丢**，变成 `spill_refs`（`{ref, kind, summary, tokens}`，摘要不占注入预算），需要时 `memory.expand` 取回。引用是**无状态的**（直接指向图与块存储），所以 server 重启、换会话都能取——代价是库里删了就取不到，此时如实报 `missing` 而不编。
- **块只在与命中实体有来源交集时进注入**：向量召回的块（`top_k`）不等于命中，与锚点/证据点毫无来源交集的块塞进上下文就是拿预算买噪声。被挡下的仍在 `hits.chunks`（标 `linked=false`），warnings 里说清几块；`memory.expand` 仍可按 `chunk:<id>` 取回。
- **溯源跟着内容走**：`hits` 里每个实体/关系、`expand` 取回的每一条都带 `origin`（`extracted`/`manual`/`mixed`/`unknown`）与 `provenance{docs,chunks,unresolved}`——agent 能分清“从文档里读到的”和“人手工断言的”，这是置信度的地基。读图挂了就回 `unknown`，不假称有来源。
- **预算透传**：`budget={top_k, max_hops, max_paths, max_context_tokens}` 会落到 `RetrievalConfig`；`trace.budget_used` 回 `context_used / context_inline / context_spilled / spilled_tokens`，溢出时 `reason="budget_truncated"`，不静默丢。
- **降级必须显式**：`texts_equal` / `vdb_error` / `no_anchor` / `vector_fallback` / `budget_truncated` 任一命中 → `degraded=true` + `reason`，agent 据此降低对结果的信任。
- **`context.query` 与 `context.task` 不要给同一段文本**：两者相等时证据层会塔成空（锚点把证据全吃掉），此时会退回人类面语义并回 `reason="texts_equal"`。
- **不生成答案**：agent 模式下不调 LLM 写答案（省一次调用），只给上下文。
- **`trace.evidence_empty`**：锚点有、证据一条都没有时置 `true`（`cited` 空）——分层只停半路。不当作 degraded（上下文本身可靠），但也不让它只藏在 warnings 里。

依赖锁：`mcp>=2.3.0,<3`。依据是 2026-11-04 实测——`mcp-types` 的 `HANDSHAKE_PROTOCOL_VERSIONS` 含 `2025-11-25`（Cola 侧报的版本），裸 JSON-RPC 探针确认 `initialize` 原样回显、未降级，且工具名合规字符集含点号（SEP-986），`memory.search` 合法。`graphkb-mcp` 启动时会再自检一次协议支持，`tests/test_mcp.py` 也有对应断言——哪天 SDK 撤了 handshake 版协议，这里先报错，而不是等 agent 调不通才发现。

已知边界：任务表在进程内存里（server 重启 `job_id` 即失效）；`memory.ingest` 的 `origin` 参数（`doc`/`session`/`note`）目前只回显不落库——它与图上的 `origin`（`extracted`/`manual`）不是同一个维度：后者由 LightRAG 的 `source_id` 判定，前者是“记忆从哪来”；`spill_refs` 能取回的只有“还在库里”的东西（实体/边/chunk 被删就报 `missing`）；token 数是粗估（CJK 按 1 字 ≈ 1 token，ASCII 按 4 字符 ≈ 1 token），偏保守不偏激进；暂无鉴权，只适合本机 stdio。

## 11. 触发器：三钩子 + 一兜底（M5）

记忆不是“查一下就在”，得在对的时候把它叫醒。`graphkb/triggers.py` 回答的就是“什么时候查”：

| 钩子 | 时机 | 锚（query 位） | 证据（task 位） |
| --- | --- | --- | --- |
| **H1 起手查** | Plan 入口 | 任务里探到的实体名 | 任务描述 |
| **H2 卡壳查** | 报错 / 重试 | 错误信息里的实体名 | 错误 + 上下文 |
| **H3 回想查** | 上下文命中图实体时 | 命中实体名 | 当前上下文 |
| **H0 显式点名** | 随时 | 实体名；没有就点名原文 | 点名文本（逃生口，不占总闸） |

三条硬约定：

- **触发器 ≠ 判据**：触发器是调度（误触发只多花一次查询），判据是语义（必须可复算）。所以这里允许廉价启发式；「阈值是运气不是判据」约束的是判据。
- **探不到实体就不查**：自动钩子（H1/H2/H3）只在文本里字面命中图上实体名时才真的查——否则 `query == task` 会触发 `texts_equal` 退化，退回人类面语义时**白花一次 LLM 生成答案**。记一笔 `skipped="no_entity"` 就算交代（事件里留着它看的是什么），总闸不扣格。H0 不受这条限制。
- **会话总闸 K=5**（`GKB_TRIGGER_K`）：只管「查几次」，每次查询另带 `budget` 管「查多重」。被拦下、探针不亮都**照样记事件**——「这次为什么没想起」必须和「为什么想起」一样看得见。

手动抬一次钩子（最小 runner；真 harness 的状态机怎么接是它自己的事）：

```bash
python -m graphkb.cli trigger plan "帮我整理张三的入职材料"          # H1
python -m graphkb.cli trigger stuck "KeyError: 张三 字段缺失"        # H2
python -m graphkb.cli trigger context "刚才那张表里张三的日期不对"    # H3
python -m graphkb.cli trigger named "张三在哪工作" --gate 0          # H0（总闸为 0 也照查）
```

输出是完整的触发事件（`hook / anchor / entities / queried / skipped / hit / degraded / gate_left / context_tokens`）+ `memory.search` 的原样结果。

## 12. 安全注意

- LLM/embedding 密钥只放本地 `.env`（已 gitignore），不要提交、不要贴进文档。
- `serve` 默认绑 `127.0.0.1`，别在公网机器上直接 `--host 0.0.0.0`——UI 没有任何鉴权。
- `data/` 里是全库内容与向量，迁移/备份时按敏感数据对待。

## 13. 端到端跑一遍（M6）

一条命令把「干活 → 存记忆 → 下次想起 → 注入有预算」走完：

```bash
python scripts/demo_agent_memory.py --workspace data   # 只跑读侧，不花 LLM
python scripts/demo_agent_memory.py --ingest           # 连写侧一起（真调一次抽取，几十秒）
```

它会跑这五步并打印每个事件的账：H1 起手查 → H2 卡壳查 → H3 回想查 → 离题 H3（探针不亮、不花预算）→ H0 点名；再把总闸耗尽，看自动钩子被拦、H0 照样能查。`--ingest` 额外演示：把一段会话记录写进图，然后用 H0 问回来，验证「上次学到的这次真能想起」。

一次真实运行的账（2026-11-06，`data/` 那 17 个实体的小图）：

| 步骤 | 锤 | 探到实体 | 查了吗 | 注入 token / 预算 | 总闸余 |
| --- | --- | --- | --- | --- | --- |
| ① 起手 H1 | 张三 北京 | 2 | 查 | 247 / 800 | 4 |
| ② 埋坑 H2 | 张三 | 1 | 查 | 119 / 800 | 3 |
| ③ 回想 H3 | 张三 | 1 | 查 | 119 / 800 | 2 |
| ④ 离题 H3 | — | 0 | **不查** | — | 2 |
| ⑤ 点名 H0 | 张三 | 1 | 查（不占总闸） | 119 / 800 | 2 |
| ⑥ 总闸耗尽 | 张三 | 1 | **被拦** `gate_exhausted` | — | 0 |
| ⑦ 被拦后点名 H0 | 张三 | 1 | 查（豁免） | 119 / 800 | 0 |

写入闭环实测（临时库、真 LLM）：一段两句话的复盘 → 7 实体/6 关系；再用 H0 问回去，注入 159 token 且包含刚学到的「社保」——探针重载后 H1 一次就探到 4 个实体。
