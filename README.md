# graph-knowledge-base（graphkb）

透明、可手工编辑的个人知识库：把文档抽成图谱，**检索过程看得见**，**图人也能改**。

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
git clone <your-repo> && cd graph-knowledge-base
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .                                  # 核心 + server + 文件解析依赖
pip install -e ".[dev]"                            # 加 pytest
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
```

装好包后同样的命令可写作 `graphkb query ...`。

## 6. 验证

```bash
python -m pytest -q                                   # 单元测试（当前 51 passed）
python holdout/evaluate.py slice-7-retrieval-visualization --version slice-7-v1
```

holdout 是 IDSD 的「考卷区」：场景由 `expectations.md` 派生、不回看实现，构建期对代理不可见（见 `holdout/README.md` 与 `.claudeignore`）。判卷结果存档在 `holdout/results/<版本>/report.json`。

## 7. 代码地图

```
graphkb/
  config.py      # env -> Config（含 RetrievalConfig）
  rag.py         # 按配置构建并初始化 LightRAG 实例
  providers/     # llm/embedding 适配：anthropic | openai_compat | ollama | mock
  ingest.py      # 文档 -> 图（增量、实体对齐）
  documents.py   # 文档生命周期：列表 / 覆盖更新 / 删除后图收敛
  merge.py       # 显式合并实体（复用 LightRAG amerge_entities）
  query.py       # 检索 + 命中分层（锚点 / 答案引用 / 最短路）-> trace
  render.py      # 把 trace 渲染成 CLI 可读的透明窗
  server.py      # FastAPI：/api/graph /api/query /api/documents /api/entities ... + 静态托管
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
- 进度：`idsd/idsd-status.yaml`（S1–S7 已验收收官，S8「文档摄取增强」已立项待开工）。

## 9. 安全注意

- LLM/embedding 密钥只放本地 `.env`（已 gitignore），不要提交、不要贴进文档。
- `serve` 默认绑 `127.0.0.1`，别在公网机器上直接 `--host 0.0.0.0`——UI 没有任何鉴权。
- `data/` 里是全库内容与向量，迁移/备份时按敏感数据对待。
