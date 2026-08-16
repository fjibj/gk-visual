# Context: slice-6-document-lifecycle（文档生命周期闭环）

> 技术查证 + spike 实证，供构建期代理参考。

## 技术栈

复用 LightRAG `ainsert`（上传，显式 `ids`）+ `adelete_by_doc_id`（删除）+ `get_docs_by_status`（列表）。文档身份 = 标题 slug，覆盖更新 = 先删后插。

## 查证：LightRAG 文档能力

| 能力 | API | 结论 |
|------|-----|------|
| 上传（显式 doc_id） | `ainsert(input, ids=[doc_id], file_paths=[title])` | ✅ 建立 doc_status 记录 |
| 列表 | `get_docs_by_status(DocStatus.PROCESSED)` → `{doc_id: DocProcessingStatus}` | ✅ 字段含 file_path / chunks_list / content_length / content_summary |
| 删除 + 收敛 | `adelete_by_doc_id(doc_id)` | ✅ spike 实证：删文档 + 派生 chunks/图元素，部分受影响实体用剩余文档缓存重建 |
| 覆盖更新 | 同 doc_id 直接重插 | ❌ duplicate 检测拦截（「Created N duplicate document records」）→ 必须**先删后插** |

## 实体贡献计数

实体/关系节点带 `source_id`（用 `<SEP>` 分隔多个 chunk id）。文档贡献数 = 节点 source_id 拆分后与文档 `chunks_list` 求交非空。

## Spike 实证（真实 LLM + bge-m3）

- 上传 sample1 + sample2 → 图 9 实体/10 关系；doc_status 两条（chunks_list 各 1 个 chunk）。
- 删 sample1 → 图收敛到 5 实体：独有（张三/张一鸣/南开大学）消失，共享（北京/李四/字节跳动公司）保留。✅
- 覆盖更新（删 sample1 v1 + 插 v2）→ 图收敛到 v2，文档仍一篇。✅
- 直接同 doc_id 重插 → duplicate 拦截。❌

## 决策（已拍板并记录）

1. **文档身份** = 标题 slug（保中文/字母/数字，其余转 `-`）；同标题 = 同文档。
2. **覆盖更新** = 先 `adelete_by_doc_id` 再 `ainsert`（spike 证实直接重插被拦截）。
3. **上传方式** = 前端「标题 + 粘贴文本」（文件上传留后续，非本切片）。
4. **贡献计数** = 节点 source_id 与 chunks_list 求交。

## 对实现的影响

- 新增 `graphkb/documents.py`（upsert/list/delete 封装）+ server 3 端点 + 前端文档面板。
- holdout 判卷**必须用真实 LLM**（文档抽取是 LLM 的活，mock 抽不出实体、测不了图收敛）；bge-m3 用 Ollama。
