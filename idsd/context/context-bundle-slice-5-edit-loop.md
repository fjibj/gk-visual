# Context: slice-5-edit-loop（编辑回路）

> 技术查证 + spike 实证，供构建期代理参考。

## 技术栈

无新增依赖：编辑复用 S4 的 LightRAG 编辑 API，检索复用 S1/S3 的 `graphkb/query.py`（`aquery_data` + `_score_trace`）。判卷沿用 S1 模式：`ainsert_custom_kg` 注入确定性 KG + mock LLM + 真实 bge-m3（Ollama）。

## 查证：编辑 API 是否同步向量库

| API | 图 | 向量库 | 结论 |
|-----|----|--------|------|
| `acreate_entity` | 建节点 | upsert entities_vdb | ✅ |
| `aedit_entity` | 改节点 | **re-embed** entities_vdb（docstring 明确） | ✅ |
| `adelete_by_entity` | 删节点+关系 | 删 entities_vdb + relationships_vdb | ✅ |
| `acreate_relation` | 建边 | upsert relationships_vdb | ✅ |
| `amerge_entities` | 删源+关系重指 | 删源向量 + upsert 目标 | ✅ |

## 查证：检索如何用图/向量

`aquery_data`（`lightrag.py:3701`）dual-level：local 走 hl_keywords → entities_vdb 相似 → **图遍历邻居**；global 走关系/社区；naive 走 chunks。`graphkb/query.py::_score_trace` 再复用 entities_vdb / relationships_vdb 补逐项余弦分数。

## Spike 实证（真实 bge-m3 + mock LLM + 显式 hl_keywords）

| 验收点 | 结果 | 证据 |
|--------|------|------|
| 改实体描述 → 分数变化 | ✅ | 张三 score 0.675→0.639，desc 变 |
| 删实体 → 不命中 | ✅ | 北京从 entities 消失，其关系也消失 |
| 合并 → 命中新名 | ✅ | 张三→李四：李四命中、张三消失、关系重指 |
| 建实体（孤立）→ 可命中 | ❌ | 上海孤立节点不召回 |
| 建实体 + 关系 → 可命中 | ✅ | 建「字节跳动→上海」后，上海命中 score=0.334、关系命中 score=0.775 |

## 关键边界（诚实记录）

- **孤立实体不被 dual-level 检索召回**：LightRAG local 检索靠「hl_keyword 命中节点 → 沿边扩展邻居」，孤立节点无邻居、扩展为空 → 不召回。这是 LightRAG 固有行为，**不强行补**（补 = 改检索，违背约束 1 复用 LightRAG）。
- 故验收点 4 精确化为「新建实体（连同关系）→ 检索可命中」；「新建孤立实体」作为边界场景记录（不召回是已知行为，不算失败）。

## 对实现的影响

- 回路在数据层**已闭环**（编辑 API 同步图 + 向量库，检索反映）。S5 **无需新写业务代码**，交付 = pytest + holdout 判卷锁定闭环 + 诚实边界。
- holdout 沿用 S1 harness（`ainsert_custom_kg` + mock LLM + bge-m3 + 显式 hl_keywords），编辑用 `rag.aedit_entity` / `adelete_by_entity` / `amerge_entities` / `acreate_entity` + `acreate_relation`。
