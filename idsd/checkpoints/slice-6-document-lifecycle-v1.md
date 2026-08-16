# Checkpoint: slice-6-document-lifecycle v1

> 2026-08-17 · 文档生命周期闭环（上传→图、列表、删除→图收敛、覆盖更新）。

## 完成情况

1. **后端** `graphkb/documents.py`：`upsert_document`（上传/覆盖，先删后插）、`list_documents`（含贡献实体/关系数）、`delete_document`；`server.py` 加 `POST/GET/DELETE /api/documents`。
2. **前端**：工具栏「文档」按钮 + 文档管理面板（上传标题+文本、列表含实体/关系数、删除）。
3. **测试**：`tests/test_documents.py` 4 用例（slugify/覆盖逻辑/贡献计数，离线 _FakeRag）；holdout 7 场景判卷（真实 LLM）。

### 验收点覆盖

| 验收点 | 状态 | 实证 |
|--------|------|------|
| 上传 → 图 | ✅ | s1：上传 sample1 → 实体出现 |
| 文档列表可见 | ✅ | s2：列出 2 篇，含各自实体/关系数 |
| 删除 → 图收敛 | ✅ | s3：删 sample1 → 独有实体消失；b2：共享实体保留 |
| 覆盖更新 | ✅ | s4：同标题重传 created=False、仍是一篇 |

### 判卷结果

- pytest **39 passed**（35 旧 + 4 新）。
- holdout **7/7 passed**（4 success / 1 failure / 2 boundary）。

## 决策（已拍板，用户授权自主决策）

1. **文档身份** = 标题 slug（保中文/字母/数字，其余转 `-`）；同标题 = 同文档。
2. **覆盖更新** = 先 `adelete_by_doc_id` 再 `ainsert`（spike 证实同 doc_id 直接重插被 duplicate 检测拦截）。
3. **上传方式** = 前端「标题 + 粘贴文本」（文件上传留后续，非本切片）。
4. **贡献计数** = 节点 source_id（`<SEP>` 分隔）与文档 chunks_list 求交。

## 诚实交代（缺口 / 风险）

1. **LightRAG doc_status 全局缓存跨实例共享**（本切片发现）：同 workspace（默认空）下，同进程顺序 init 多个 LightRAG 实例时，doc_status 记录会跨实例泄漏（spike 复现：s2 的 sample2 残留在 s4）。**修复**：给每个实例设唯一 `workspace`（`graphkb/rag.py` 已透传 workspace，`Config.workspace` 默认空，生产单实例不受影响）。此为真实坑，已记 backlog 备查。
2. **覆盖更新必须先删后插**：直接同 doc_id 重插被 LightRAG duplicate 检测拦截，若未来要"原地更新"需改机制。
3. **贡献实体数是近似**：按 source_id 与 chunks_list 求交，受 LLM 抽取粒度影响（同一实体可能因描述略异被抽成两个节点，如"字节跳动" vs "字节跳动公司"）。
4. **文件上传未做**：当前只支持粘贴文本；二进制文件（PDF/Word）解析留后续。
5. **holdout 依赖真实 LLM**：文档抽取是 LLM 的活，判卷必须用火山 LLM + Ollama，较慢且消耗 token，无法全离线。

## 提交链

（构建 + 判卷提交，见 git log）
