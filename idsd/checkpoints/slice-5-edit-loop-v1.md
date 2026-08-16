# Checkpoint: slice-5-edit-loop v1

> 2026-08-16 · 编辑回路（编辑 → 检索随之变化）· 无新业务代码，验证 + 判卷锁定闭环。

## 完成情况

核心结论：**编辑回路在数据层已闭环**——LightRAG 编辑 API 同步图 + 向量库（`aedit_entity` re-embed、`adelete_by_entity` 删向量、`amerge_entities` 删源 + 关系重指），`aquery_data` dual-level 检索反映这些变化。S5 **无需新写业务代码**，交付 = 查证 + pytest + holdout 判卷锁定闭环。

1. **context 查证 + spike**：读 LightRAG 编辑 API（确认同步向量库）+ `aquery_data`（dual-level），spike 实证 4 验收点回路。
2. **pytest**（`tests/test_edit_loop.py`）：4 用例锁定「编辑→图」数据层（改/删/合并/建的图状态），离线 mock embedding。
3. **holdout**（`holdout/scenarios/slice-5-edit-loop/`）：7 场景判卷（真实 bge-m3）。

### 验收点覆盖

| 验收点 | 状态 | 实证 |
|--------|------|------|
| 改实体 → 检索变 | ✅ | s1：张三 desc 软件工程师→数据科学家，score=0.639 |
| 删实体 → 不命中 | ✅ | s2：北京从命中集消失 |
| 合并 → 命中新名 | ✅ | s3：命中李四、不命中张三 |
| 建实体+关系 → 可命中 | ✅ | s4：上海+关系命中 |

### 判卷结果

- pytest **35 passed**（31 旧 + 4 新）。
- holdout **7/7 passed**（4 success / 1 failure / 2 boundary）。

## 诚实交代（缺口 / 风险）

1. **孤立实体不召回**（LightRAG 固有边界）：dual-level local 检索靠「hl_keyword 命中节点 → 沿边扩展邻居」，孤立节点无邻居 → 不召回。未强行补（补 = 改检索，违背约束 1 复用 LightRAG）。b1 场景锁定此行为。
2. **分数变化依赖 re-embed**：改描述→分数变化依赖 bge-m3 re-embed（Ollama 运行）；Ollama 未起时编辑失败（真实依赖，非缺陷）。
3. **mock 向量做不了语义**：pytest 只测「编辑→图」数据层；语义检索回路必须走 holdout（真实 bge-m3），无法全离线 CI。
4. **无前端可视化**：编辑回路是数据层行为；「编辑前后 trace 对比」的前端展示留 S6 或后续（本切片明确不做）。

## 提交链

`71c00ef`(S5 ICE + 构建 + holdout)
