# Checkpoint: slice-8-document-ingestion-enhancement（v1）

> 文档摄取增强：文件格式解析主体（URL 抓取后置）。
> 状态：构建完成，holdout 7/7，**待用户验收**（2026-09-04）。

## 干了什么

### 选型：零自研解析器

原 intent 的「四个格式适配器」整段划掉。实测 LightRAG 1.5.6 自带解析层，
公开入口就是项目需要的全部：

```python
from lightrag.parser.legacy import extract_text
text: str = extract_text(file_bytes, suffix)  # 同步，服务端放 to_thread
```

- 覆盖 `txt md docx xlsx pptx pdf …`，内部按需 import pypdf / python-docx /
  python-pptx / openpyxl（docx 表格、xlsx 多 sheet 已转成带转义的 markdown 表）；
- 入参只有字节 + 后缀，不碰 LightRAG 的 `ParseContext`/`inputs/` 目录布局；
- 与约束 1（复用 LightRAG）同向——解析层也是它的；
- 决策记录见 `idsd/backlog.md` 条目 13。

### 后端

`POST /api/documents/upload`（multipart: `file` + 可选 `title`）：

1. 后缀白名单 `{txt, md, docx, xlsx, pptx, pdf}`（`SUPPORTED_UPLOAD_SUFFIXES`）；
   不在白名单/无扩展名 → 400「不支持的格式」；
2. 大小上限 `config.max_upload_mb`（env `GKB_MAX_UPLOAD_MB`，默认 50MB），
   超限 → 413；
3. `await asyncio.to_thread(extract_text, data, suffix)`——解析是 CPU 活，
   不卡事件循环；
4. 解析抛错（损坏文件）→ 400 带原因；空文本（扫描版 PDF / 空 docx）→ 400
   「抽不出文本（若是 PDF，可能是扫描版无文本层，需 OCR）」——绝不拿空串喂图；
5. 通过 → `upsert_document(rag, title或文件名stem, text)` 复用 S6 管线：
   doc_id = 标题 slug，同标题重传 = 覆盖更新。

### 前端

文档管理面板加「上传文件」行（accept 白名单一致）+ 独立按钮 + 复用 loading/
状态条/上传后刷新图与文档列表。标题框留空 = 用文件名当标题。

### 测试与考卷

- `tests/test_upload.py`（12 例）：四种真实格式内存字节（docx/xlsx/pptx/txt）
  端到端 + 损坏/不支持/无扩展名/空 docx/空 PDF（扫描版）/超限 6 条失败与边界路径。
  PDF 文本正例不在单测（需 PDF 写入库，不为测试引入 reportlab）→ 由 holdout 覆盖。
- `tests/` 合计 **67 passed**（55 + 12）。
- `holdout/scenarios/slice-8-document-ingestion-enhancement/`（7 场景，真实 LLM +
  bge-m3，每场景独立临时库）：4 success（docx→图 / xlsx→图 / 文本 PDF→图 /
  同标题重传覆盖更新）+ 1 failure（损坏 docx 在入库前抛错、库保持干净）+
  2 boundary（扫描版 PDF 空文本检出、多 sheet xlsx 全表进文本）。**slice-8-v1 判卷 7/7**。
- 文本 PDF 由考卷内手写的最小合法 PDF 生成器提供（xref 逐字节精确，
  `holdout/scenarios/slice-8-document-ingestion-enhancement/_common.py`），
  纯标准库、零新增依赖。

### 顺手修的工程债（独立提交 9923e40）

- `pyproject.toml`：`lightrag-hku[api]>=1.5.6` + 显式 fastapi/uvicorn/
  python-multipart 与四个解析库；`[project.scripts] graphkb`；readme 字段。
- `graphkb/__main__.py`；CLI 新增 `serve` 子命令。
- 检索预算 `HIT_TOP_K / MAX_HOPS / MAX_PATHS` 配置化（`config.RetrievalConfig` +
  env），从 `query()` 透传到 `_shortest_paths()`，预算写进 `hit_layers`；
  顺带修了 `_hit_trace` 里锚点循环变量 `b` 遮蔽预算变量的 bug（假名 `other`）。
- `README.md`；`.env.example` 补全；13 个 `_scratch_*.py` 移入回收站。

## 验收清单（待用户）

1. 打开 http://127.0.0.1:8000 → 文档管理 → 选一个真实 .docx/.pdf/.xlsx →
   「上传文件」→ 解析后图长出、文档列表出现（标题正确、含实体/关系计数）；
2. 同标题重传一份内容改过的文件 → 提示「已更新」而非「已上传」，文档数不 +1；
3. 传一个损坏文件 / .exe → 明确报错文案（不静默）；
4. （可选）传一个扫描版 PDF → 提示需 OCR；
5. 列表里已上传的文件可删除 → 图收敛（复用 S6）。

## 遗留 / 未做

- URL 抓取：后置（intent 已拍板）。做的时候要带 SSRF 防线与抓取链，安全面大，
  建议单独过一遍设计（会不会又要 1 条 URL 规则预算？）。
- 前端上传暂无拖拽/多文件；单文件选择够用，先不加。
- 解析层异常文案里会透出底层库异常（如 BadZipFile 的细节），对个人工具可接受；
  若想对外分享，应改成不给实现细节的文案。
