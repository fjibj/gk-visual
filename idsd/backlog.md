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

- **状态**：切片缺口，未在任何切片（S1–S5）覆盖。用户 2026-08-16 指出。
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

- **状态**：切片缺口，未在任何切片（S1–S5）覆盖。用户 2026-08-17 指出。
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

- **状态**：已立项 S8（用户 2026-08-17 拍板「S8 可以先立，等我验证完 S6、S7 之后再做」）。
- **内容**：当前文档上传只支持粘贴纯文本；真实文件（docx/xlsx/pptx/pdf/txt/md）解析 + URL 抓取是缺口。
- **优先级**：文件格式解析 = 主体先做（更安全更常用）；URL 抓取 = 后置子项（安全面大：SSRF/超时/大小限制/robots）。
- **实现线索**：格式适配层只做「字节/URL → 纯文本」，下游复用 S6 `ingest_document` + `POST /api/documents`；解析用 python-docx/openpyxl/pypdf/python-pptx。
- **详见**：`idsd/intents/slice-8-document-ingestion-enhancement/`。
