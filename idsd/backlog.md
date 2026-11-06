# 待办（Backlog）

> 记录"先不加、后面再考虑"的候选，以及已识别的切片缺口。
> 每项标注：来源、依据、状态。

## 1. 合并预览（含自环保留提示）

- **状态**：未做，后续考虑（用户 2026-08-16 拍板"先不加，记录一下"）。
- **内容**：在 S4 合并面板点"合并"之前，展示预览：
  - 会转移到目标实体的关系（新增）；
  - 因自环被丢弃的关系（源之间、或源与目标之间已有的边，替换后变成 `X~X` 自环，LightRAG 直接 `continue` 跳过）；
  - 与目标已有关系去重合并的关系（description 拼接、keywords/source_id/file_path 去重、weight 取 max）。
- **依据**：透明原则——合并是破坏性操作（源实体被删），预览让后果可见。
- **实现线索**：`graphkb/merge.py::merge_entities` 已返回 `relationships_transferred` / `sources_remaining`；预览需额外算出"自环丢弃数"与"去重合并数"，目前 `amerge_entities` 不返回这两个数，需在 `_relations_of` 前后对比自算。

## 2. 文档生命周期（上传 / 列表 / 删除文档）

- **状态**：**已实现**（S6，2026-08-30 用户验收通过）。下方为立项时的缺口盘点，保留备查。
- **现状盘点**：
  - 文档→图：S1 已做，但**仅 CLI**（`python -m graphkb.cli ingest <path>` 读本地 UTF-8 文本），无前端上传入口。
  - 增量合并/同名对齐：S2 已做，但**仅 CLI**；同名实体自动聚合靠 LightRAG `ainsert`（只对完全同名生效），变体靠显式 `merge` 命令。
  - 删除文档 → 节点/关系处理：**完全没做**，无 CLI 命令、无 API、无前端。
  - 前端（S4）：只有图谱可视化 + 编辑，无文档上传/列表/删除界面。
- **关键发现**：LightRAG 已内置 `adelete_by_doc_id(doc_id)`（`lightrag.py:5387`），会删文档 + 全部派生 chunks/图元素，且"部分受影响的实体/关系用剩余文档的 LLM 缓存重建"——这正是"删文档后图怎么收敛"的复杂逻辑，无需自己发明，封装即可。
- **已立项**：2026-08-16 用户拍板新增 S6「文档生命周期闭环」，放 S5 之后（硬依赖 S1 ingest + S4 前端）。详见 `idsd/intents/slice-6-document-lifecycle/`。

## 3. 文档版本更新 + 多版本并存

- **状态**：已定（用户 2026-08-16 拍板：**覆盖更新优先、版本历史后置**）。
- **现状查证（LightRAG doc_id 机制，`pipeline.py:933-949`）**：
  - `ainsert(ids=…)` 支持**显式传入文档 ID**——这是版本管理的钥匙。
  - 不传 ids 时：有 file_path → `doc-` + md5(路径)（同路径=同 id）；纯文本 → `doc-` + md5(内容)（内容变=新 id）。
  - 内置**重复检测**：同文件名 / 同内容 hash 会被判 duplicate 跳过，不重复 ingest。
  - 当前 `ingest_document(rag, text)` 只传文本 → doc_id=md5(内容)：内容一改就当**全新文档**（多版本悄然并存，旧版独有实体不消失，同名实体聚合）。
- **已定决策**：
  1. 同文档重传 = **覆盖更新**（旧版图收敛到新版，实现路径 `adelete_by_doc_id(旧) → ainsert(新, ids=稳定id)`）。
  2. **版本历史后置**：不做 v1/v2 并存与回看，后置 backlog。
  3. 文档身份用稳定标识（文件名/标题），不用内容 hash；具体落地 + LightRAG duplicate 检测对「同 id 重插」的行为，开工时 spike 定。

## 4. 孤立实体不被检索召回

- **状态**：暂不处理（用户 2026-08-17 拍板「暂先不处理，记下来」）。
- **内容**：新建但未连任何关系的孤立实体，在 dual-level 检索里不被召回（local 检索靠「关键词命中节点 → 沿边扩展邻居」，孤立节点无邻居 → 扩展为空）。
- **依据**：S5 spike 实证 + 检查点缺口 1。LightRAG 固有行为，未强行改（改 = 改检索，违背约束 1 复用 LightRAG）。
- **影响**：前端「新建实体」若不连关系，图里可见但检索搜不到。

## 5. 检索前端可视化缺口（检索框 + 图上路径高亮 + 多轮颜色演进）

- **状态**：**已实现**（S7，2026-08-30 用户验收通过，含三轮返工）。演进全过程见 `idsd/notes/retrieval-hit-and-highlight-encoding-log.md`。
- **内容**：
  - 检索目前仅 CLI（`python -m graphkb.cli query`）；`server.py` 无 `/api/query` 端点；前端无检索框。
  - 「检索路径在图上高亮 + 多轮对话颜色演进（当前步最深、历史越远越浅）」是 overall Goal 4 的一部分：S3 intent 明确「多轮颜色演进留到 S4 有 UI 后」，但 S4 只做了图谱可视化 + 编辑，未接检索路径高亮——**切片衔接遗漏**。
- **已立项**：2026-08-17 用户拍板新增 S7「检索可视化闭环」，顺序 S6→S7。依赖 S1 trace + S3 分数 + S4 前端 + S5 编辑回路。详见 `idsd/intents/slice-7-retrieval-visualization/`。

## 6. LightRAG doc_status 全局缓存跨实例共享

- **状态**：已发现并修复（S6 施工中发现，2026-08-17）。
- **内容**：同 workspace（默认空）下，同进程顺序 init 多个 LightRAG 实例时，doc_status 等存储的全局缓存会跨实例泄漏（spike 复现：前一个场景的 sample2 残留在后一个场景的 doc_status 里）。
- **修复**：`graphkb/rag.py` 透传 `workspace`，`Config.workspace` 默认空；测试/考卷用唯一 workspace 隔离。生产单实例不受影响。
- **备注**：未来若在单进程内跑多库（多 working_dir），必须给每库设唯一 workspace。

## 7. 结构化实体属性（key-value）

- **状态**：保持现状（用户 2026-08-17 拍板「属性保持现状」）。
- **内容**：LightRAG 实体只有 name/type/description 三字段（边只有 src/tgt/keywords/description/weight），无自定义 key-value 属性槽；「成立时间/员工数/总部地址」等属性被 LLM 揉进 description 自由文本（prompt 原文：`entity_description: ... attributes and activities`）。`utils_graph.py::acreate_entity` 只取 entity_type/description/source_id/file_path/created_at，其他字段丢弃。
- **权衡**：description 承载属性 → 可检索、零成本，但不可结构化过滤/排序；结构化属性表 → 可过滤但违背约束 1（状态跑出 LightRAG）、不参与检索、需同步维护，属天花板。
- **结论**：后置，除非出现明确的「按属性过滤/统计」场景。

## 8. 文档摄取增强（文件格式 + URL 抓取）

- **状态**：**文件格式部分已实现**（S8，2026-09-04 提交 `5be9746`，holdout 7/7，人工验收用户主动延后）；**URL 抓取 = 后置待拍板**。
- **立项时盘点**：当前文档上传只支持粘贴纯文本；真实文件（docx/xlsx/pptx/pdf/txt/md）解析 + URL 抓取是缺口。
- **优先级**：文件格式解析 = 主体先做（已完成）；URL 抓取 = 后置子项（安全面大：SSRF/超时/大小限制/robots）。
- **实现结果**：适配层只做了「字节 → 纯文本」一步，直接调 `lightrag.parser.legacy.extract_text`（见条目 13），下游复用 S6 `upsert_document`；新增 `POST /api/documents/upload`。
- **URL 子项开工前必读**：legacy 解析层对 `html` **只做 UTF-8 解码、不去标签**（实测 `_BINARY_EXTRACTORS` 只有 pdf/docx/pptx/xlsx 四个），所以拓回网页后还得自备一步「HTML → 正文」（要嘛加 bs4/markdownify/readability 依赖，要嘛写一小段去标签）；另需 SSRF 白名单与超时/大小上限。
- **详见**：`idsd/intents/slice-8-document-ingestion-enhancement/`、`idsd/checkpoints/slice-8-document-ingestion-enhancement-v1.md`。

## 9. 实体/边溯源标签（LLM 抽取 vs 手工创建）

- **状态**：**已实现（M4，2026-11-06）**。原为候选（用户 2026-08-22 拍板「记下来，后面再做」），来源：graphify 对比分析。
- **灵感**：graphify 每条边打 `EXTRACTED`（源码明确存在）/ `INFERRED`（推断）标签，「永远知道哪些是读到的、哪些是猜的」——与本项目约束 2「透明」同源。
- **落地方式**：不另存账本，**从 LightRAG 自己留的痕读出来**（`graphkb/provenance.py`）：
  - 抽取来的：`source_id` = 若干 chunk_id（`<SEP>` 分隔）；
  - 手工新建的：`source_id` = `"manual_creation"`（LightRAG `utils_graph.acreate_entity/acreate_relation` 的默认哨兵）；
  - 两者都有（编辑过抽取实体、合并把手工实体并进来）：→ `mixed`。
- **四种 origin**：`extracted` / `manual` / `mixed` / `unknown`（没有任何来源记录的老数据）。无阈值、无 LLM。
- **来源文档**：不走节点自己的 `file_path`（老数据里是 `unknown_source`），一律批量查 `rag.text_chunks.get_by_ids` 拿 `full_doc_id`；块已被删的计入 `unresolved`，如实说「这部分已无据可查」。
- **前端**：人工痕迹 = 标签后缀 `✎` + 紫色底晕（**不用边框**——边框通道已被 S7 的命中分层占用：实线环=锚点、虚线环=引用/路径）；详情面板顶部只读块显示「人工创建 / 文档抽取 + 人工改动」与来源文档；左上角图例只在图里存在人工元素时出现。
- **契约**：`/api/graph` 的每个 node/edge、`memory.search` 的 `hits`、`memory.expand` 的 `items` 都带 `origin` + `provenance{manual,docs,doc_ids,chunks,unresolved}`。
- **代价**：只区分到「有没有人碰过」，区分不出「谁、什么时候碰的」——那需要真审计日志，不在本阶段。

## 10. 路径查询（A 到 B 怎么关联起来）

- **状态**：候选（用户 2026-08-22 拍板「记下来，后面再做」）。来源：graphify 对比分析（`graphify path A B` 最短路）。
- **内容**：前端加「路径查询」：输入两个实体名，图上高亮它们之间的最短路径（逐跳展示）。
- **实现线索**：与语义检索无关、零 LLM 成本——在 LightRAG 的 `chunk_entity_relation_graph`（NetworkX 图）上跑 `shortest_path`；新增 `/api/path?from=X&to=Y` 端点，返回路径节点/边序列；前端复用 S7 的高亮机制（`hit` class + `hitLayer`/`hitAge` 驱动的形态与色温通道，见 S7 检查点修订三）。适合做小切片（后端 1 端点 + 前端 1 输入框 + 复用高亮）。
- **备注**：graphify 纯图遍历无向量库的确定性优势，正是这类查询；本项目图小（个人库），BFS 成本可忽略。

## 11. 单文件图谱快照导出（graph.html 思路）

- **状态**：候选（用户 2026-08-22 拍板「记下来，后面再做」）。来源：graphify 对比分析。
- **灵感**：graphify 整个图交付为一个可分享的 `graph.html`（内嵌数据 + 交互，浏览器直接打开）。
- **内容**：一键导出当前图谱快照为单文件 HTML：内嵌图数据 + Cytoscape 渲染，发给任何人/换机器可直接打开浏览（只读），无需起 server。
- **实现线索**：后端加 `/api/export/html`（或 CLI 命令）：读全图 JSON → 塞进预编译的 HTML 模板（内联 cytoscape.js + 数据 + 只读版交互：缩放/拖拽/点选详情）；不含检索（无后端），编辑功能裁剪。注意数据敏感：导出文件等于把全库内容带出门，导出前应提示。

## 12. 「答案在复述而非给证据」的假信心高亮

- **状态**：候选，**需用户拍板才能做**（新增规则族，撞总体约束 6「规则预算 ≤ 1」）。源自 S7 验收修订三。
- **现象**：问「张三认识姚明吗」，LLM 诚实回答「无法确认，图里没有姚明」，但它会在答案里复述已知信息（「张三是一名软件工程师，居住在北京…」）——按现行判据，这些被复述的实体全算「答案引用」，于是图上出现 4 实体 3 边的红圈，看着像找到了依据。
- **已做的缓解**：`hit_layers.unmatched_keywords` 会在面板显式提示「问题里的「姚明」图上没有对应实体」，并附一句「下方红圈不表示检索找到了依据」。零新规则，靠现有 ll_keywords 对比图实体名得出。
- **未做**：判断「这句答案是在引用证据还是在声明无据」需要否定/情态语义（“无法确认”“没有记载”），要么关键词表（脆、新增规则族）、要么叫 LLM 分类（多一次调用）。两者都比现在贵，所以先记账不动手。
- **备选路线**：让透明窗多一层「无据」状态（红圈降级成空心环 + 面板顶部标「答案未给出图依据」），先用规则：答案中出现 `无法确认|未出现|没有.*描述|无法基于现有资料` 这类模板句式时降级——但 LightRAG 的提示词并不保证这些句式，属低置信启发。

## 13. S8 选型证据：LightRAG 自带解析层，可零自研

- **状态**：**已落地**（S8 就是按这个选型做的，`5be9746`，holdout 7/7）。以下为当时的实测记录，保留备查。
- **实测入口**（`site-packages/lightrag/parser/legacy/extractors.py`）：
  ```python
  from lightrag.parser.legacy import extract_text, LegacyExtractionError
  text: str = extract_text(file_bytes, suffix, pdf_password=None)   # 同步，官方注释要求调用方放线程里跑
  ```
  入参是**字节 + 后缀**，不依赖 LightRAG 的 `ParseContext`/pipeline/`inputs/` 目录——意味着我们可以直接复用，不必把文件落进它的目录布局。
- **支持范围**：`legacy` 引擎覆盖 `txt md mdx pdf docx pptx xlsx rtf odt tex epub html htm csv json xml yaml yml log conf ini properties sql …`；内部按需延迟 import `pypdf` / `docx` / `pptx` / `openpyxl`（docx 表格、xlsx 多 sheet 已转成带转义的 markdown 表格），其余后缀走 `_decode_text`。
- **另有**：`native` 引擎（docx/md/textpack，带 LLM 标题判定）、`external/mineru|docling`（远程服务，需 `MINERU_LOCAL_ENDPOINT`/`MINERU_API_TOKEN`/`DOCLING_ENDPOINT`，支持 pdf/图片）。**S8 不需要它们**——结构化版面还原属天花板，先用 legacy 的纯文本。
- **调试便利**：`python -m lightrag.parser.cli` 可单文件跨引擎跑解析，S8 排错时可直接用。
- **开工前置（硬）**（两者均已于 2026-09-04 完成）：
  1. `python-multipart` **当前未安装**，而 FastAPI 的 `UploadFile`/`Form` 必须有它——上传端点一上就报 `Form data requires "python-multipart" to be installed`。
  2. `pyproject.toml` 依赖声明不全：本项目 `dependencies = ["lightrag-hku", "httpx", "python-dotenv"]`，而 `fastapi`/`uvicorn`/`python-docx`/`python-pptx`/`openpyxl`/`pypdf` **全部只存在于 `lightrag-hku[api]` extra**。当前机器能跑是因为装了带 extra 的版本；换机 `pip install -e .` 后 server 与解析都会缺包。修法二选一：把依赖写成 `lightrag-hku[api]`，或显式列出 fastapi/uvicorn/python-multipart + 四个解析库。
- **待 spike**：大文件解析耗时（同步函数放 `asyncio.to_thread`，UI 已有 loading 态可复用）；空文本/纯图 PDF（pypdf 抽不出字）的报错文案；大小上限具体值。（均已在 S8 实现：to_thread + 400「抽不出文本」 + `GKB_MAX_UPLOAD_MB=50`）

## 14. 工程债：无 README、无 CI、参数未配置化

- **状态**：**大部分已还（2026-09-04）**。剩下的 CI 需等仓库有远端才能做。
- **已还**：
  - `README.md` 已写（含安装/配置表/启动/CLI/验证/约束速览）。
  - 依赖声明已修：`pyproject.toml` 改 `lightrag-hku[api]>=1.5.6`，显式列出 fastapi / uvicorn / python-multipart / pypdf / python-docx / python-pptx / openpyxl；`python-multipart` 已安装（S8 上传必需）；加 `[project.scripts] graphkb` 与 `graphkb/__main__.py`（`python -m graphkb` 可用）。
  - `HIT_TOP_K / MAX_HOPS / MAX_PATHS` 已配置化：`config.RetrievalConfig` + env `GKB_HIT_TOP_K/GKB_MAX_HOPS/GKB_MAX_PATHS`，从 `query()` → `_hit_trace()` → `_shortest_paths()` 全程透传；预算写进 `hit_layers`（前端显示的是实际值）。注意：改这些数不改变命中判据，只改变允许多宽。
  - `graphkb.cli` 新增 `serve` 子命令（--host/--port/--reload）；`.env.example` 补 GKB_WORKSPACE 与三个预算变量。
- **未还**：CI 入口（本仓库还没有 git remote，GitHub Actions 写了也没法跑）；前端色温/形态档位仍硬编码在 `main.ts`（跨 TS/Python 边界，收益低，后置）。

## 15. 非 UTF-8 文本文件（GBK）会被拒

- **状态**：候选，未排期。发现于 S8 实测（2026-09-06）。
- **现象**：legacy 解析层的 `_decode_text` **只认 UTF-8**（实测：`file_bytes.decode("utf-8")` 失败即抛 `LegacyExtractionError("File is not valid UTF-8 encoded text. Please convert it to UTF-8 before processing")`），空内容/纯空白也靠它报错。于是上传 GBK/GB18030 存的 `.txt/.md/.csv`（Windows 记事本旧文件的常态）会被 400 拒，且错误文案是英文。
- **为什么值得管**：中文用户脚踢频率高；而拒收本身是对的（不能拿乱码喂图），只是体验硬。
- **候选做法**：
  1. 只改文案：把这条英文错转成中文提示「请用 UTF-8 另存后重试」（零风险，不碰解析）；
  2. 在我们适配层加一次 encoding 退避：先 UTF-8，失败再试 gb18030，成功则重编码为 UTF-8 后交给 `extract_text`（约 6 行，属于一条小规则，吃得住约束 6）；
  3. 上探测库（chardet/charset-normalizer）——多一个依赖，杀鸡用牛刀。
- **建议**：1+2 一起做（先试退避，再不成给中文错），归入一个小的收尾切片或跟 URL 拓取同片做。

## 16. LightRAG 1.5.7 删了 facade `get_docs_by_status`

- **状态**：已修（2026-11-04，M0 补 CI 时被 CI 当场抓出）。
- **现象**：`pyproject.toml` 只写了 `lightrag-hku[api]>=1.5.6`，CI 装到 1.5.7 → `tests/test_upload.py` 三个上传用例脱 400，报 `'LightRAG' object has no attribute 'get_docs_by_status'`。本地是 1.5.6，所以一直没暴露。
- **实测差异**（对比两边 wheel 里的 `lightrag/lightrag.py`）：1.5.7 删掉了 `get_docs_by_status(status)`，也没在同层加替代方法；能力搬到底层 `doc_status.get_docs_by_statuses(statuses: list[DocStatus], strict=False) -> dict[str, DocProcessingStatus]`，**1.5.6 也早就有这个**。
- **改法**：`graphkb/documents.py` 三处调用改走 `rag.doc_status.get_docs_by_statuses([DocStatus.PROCESSED])`（收进 `_processed_docs()`），不把 lightrag 钉死在 1.5.6；`pyproject.toml` 同时加下界 `>=1.5.6,<1.6`——1.6 再动就等 CI 说话。
- **残留**：holdout 没在 1.5.7 上跑过（CI 只跑 pytest）；下次升级 lightrag 前，本地先跑一遍 S3/S5/S7/S8。

## 17. 符号型实体抽不出来（代码名/常量名建不了节点）

- **状态**：候选，本阶段不做。来源：探针 B 结论 §3「边界 2」（2026-11-04）。
- **现象**：4 份设计文档灌图（260 实体 / 371 关系）后跑 agent 场景检索，`unmatched_keywords` 里反复出现「文档里满篇、图上无节点」的词：`graphkb`、`K=5`、`HIT_MIN_RATIO`、`budget_truncated`、`分数阈值`、`连通性`、`最短路`、`编排层`。
- **原因**：LightRAG 的自动抽取偏自然语言实体，对代码符号（包名、常量名、`K=5` 这类）几乎不建节点；而 agent 的任务描述里恰恰满是代码符号——这是 agent 记忆的特有短板，也呼应 JitKnow 分析里的「自动抽取、类型不可控」。
- **为什么本阶段不做**：任何解法都要新增规则族（抽取前预处理 / 抽取后补节点 / 本体 schema），撞约束 6「规则预算 ≤ 1」。
- **候选方向**：
  1. 抽取前对代码符号做归一与保留（fenced code、`snake_case`、`CONST_NAME`、`K=5`）；
  2. 留到本体层 schema 阶段，给符号类实体单独定型；
  3. 只在写侧（`memory.ingest` 的 `source=session`）对代码片段做兜底节点。
- **判据**：先量真实任务里 `unmatched_keywords` 的符号类占比，持续 >20% 再谈值不值得动。

## 18. 注入密度：真图上「路径节点」吃掉了大半预算（也压住了块）

- **状态**：**已实现（2026-11-06，方案 ③）**。
- **现象**（真图夹具 80 节点 / 真库 260 节点，`budget.max_context_tokens=800`）：
  - `query=锚点A`、`task` 里点名 B、C → 命中 7 实体 / 6 关系，**13 行注入刚好塞满 668 token**，其中 `[path]` 占 **10 行**（1 锚 + 2 引用 + 10 中间节点）。
  - 三个锚点、无引用点 → 12 行注入里 9 行是 `[path]`；同时 4 条关系 + 8 块溢出（3296 token）。
  - 块（chunk）基本进不了注入：一律 `reason=budget_truncated`，溢出全落在 `chunk:` 引用上（可取回，不是丢）。
- **为什么算问题**：路径中间节点只是「这两个实体确实连得上」的连通性证据，却和锚点/引用点抢同一份额度；800 token 里真正回答问题的部分可能只有两三行。`degraded` 因此在真图上是常态（每次都 `budget_truncated`），告警失去区分度。
- **三条候选**（都不碰判据，只在注入策略层）：
  1. **拼接句去重**：`<SEP>` 拼出来的近重复段（同一实体的多份文档陈述）只留一段；
  2. **分段截断**：每段只取第一句、最多 N 段；
  3. **按层分配预算**：anchor 占大头、cited 次之、path 只留「名字 + 类型」（它只需要证明连得上，不需要完整描述），块只在有明确引用时进。
- **建议**：先做 ③（收益最大、且不丢信息：path 的描述本来就可以靠 `entity:` 取回），再叠 ①。
- **落地（方案 ③）**：`graphkb/memory_api.py` 新增 `LAYER_SHARES`（anchor 40% / cited 25% / direct 15% / path 12% / chunk 8%），path 层只带名字 + 类型；份额是**软上限**（后面几层花不完的额度当前层可以先吃，否则「预算恰好够用」会被错杀），用不完的往下传（waterfall），每层花费记进 `budget_used.context_by_layer`。同图同 800 token 的实测：1 锚 + 2 引用从「inline 13 / spill 3 块 1146」变成「inline 14 / spill 2 块 764」；3 锚场景从「inline 12 / spill 12」变成「inline 17 / spill 7」；demo 真图 H1 从 inline 9 条变 34 条。细节见 `idsd/notes/m3-inline-spill.md` §7。
- **残留**：`degraded` 在真图上仍是常态（块装不下就是 `budget_truncated`）——溢出不是丢弃，但默认 800 token 对 260 实体这种图偏紧；要不要调大默认值或按图规模自适应，另议（方案 ①/② 也还没做）。

## 19. 同进程里两个实例同 workspace：KV 静默为空

- **状态**：**已实现自动隔离（2026-11-06）**。
- **现象**（真图回归蹲到）：一个进程里先建过实例 A（库目录 a、`workspace=""`），再建实例 B（库目录 b、同样 `workspace=""`）——B 的 `text_chunks` 是 **0 条**，按 id 取块一律 `None`；图却正常（260 个节点读得到）。表现是 `memory.expand` 全报 `missing`，容易误判成「块被删了」。
- **根因**：LightRAG 的 KV 数据挂在**进程级**共享字典 `_shared_dicts[workspace:namespace]` 上，而「谁负责从磁盘加载」只是全局初始化标志 `_init_flags`。A 先把 `:text_chunks` 标成已初始化并填进去，B 看到标志就不再读自己的 JSON 文件。GraphML 是每个实例自己读文件，所以图不受影响。
- **改法**：`graphkb/rag.py::_isolate_shared_kv`，在 `init_rag` 里跑。判定不看「谁先谁后」而看**内容**：把我的磁盘文件读出来，若共享字典里缺我文件中的键（`set(mine) - set(data)` 非空），说明那份共享数据不属于我，把 `_data` 换成本实例自己的字典——读自己的文件、写也只落自己的目录；若共享字典已包含我全部键（同库重复建实例），什么都不动，保持上游共享语义。真图 live 用例已改回 `workspace=""`，靠它自动隔离跑通（日志：`8 个 KV 存储改用本实例自己的数据副本`）。
- **代价/边界**：被隔离的实例不再与其它实例共享内存（本来也指向不同目录，共享才是错的）；多进程 `initialize_share_data` 那套协议不参与（graphkb 目前单进程）。
- **还剩下的**：这是 graphkb 层的补丁，不是上游修复。可以向上游提 issue：多实例同 workspace 是合理用法，应该由 `need_init` 比对库目录而不是只看 namespace。