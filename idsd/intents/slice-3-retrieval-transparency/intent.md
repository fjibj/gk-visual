# Intent: slice-3-retrieval-transparency（检索路径可视化 / 透明窗渲染）

> 本切片是总体意图 Goal 4 的落地，关闭 Failure Condition 2（检索路径黑盒，看不到"凭什么"）。
> 前置：S1 已把检索过程暴露成结构化 trace（`aquery_data` 的 dual-level 命中），S2 已交付增量+对齐。
> 本切片**只在 trace 之上做渲染与补分数，不改检索算法**。

## Goal

把 S1 焊死的 trace 渲染成**人类可读的检索路径解释**，并补上逐项余弦分数，让"凭什么命中这些实体/关系、凭什么排这个序"可见。

三个验收点：

1. **逐项分数**：trace 的每个命中实体/关系带余弦分数（对 LightRAG 向量库 `entities_vdb` / `relationships_vdb` 做薄 instrumentation，复用其 `query` 接口，不重写检索）；
2. **渲染**：CLI 输出检索路径（dual-level：高层关键词 → 低层实体 → 命中关系 → 依据块），命中项带分数、按分数区分显著度；
3. **诚实降级**：分数拿不到时如实标注"无分数"，绝不编造；trace 空时如实显示"未命中"，绝不画假路径。

## Constraints

1. **复用 LightRAG**：逐项分数走 `entities_vdb.query` / `relationships_vdb.query`（现成接口），不重写检索/向量逻辑（约束 2）。
2. **纯 Python + CLI**：本切片仍无前端/HTTP（TS 前端到 S4 才引入）。
3. **渲染是展示层**：trace 数据源（JSON 结构）由 S1 保证，S3 只在其上渲染，不新增"规则族"（规则预算 ≤ 1）。

## Failure Conditions

1. trace 有命中，但渲染输出不含命中实体/关系列表 → 透明窗没装上。
2. 逐项分数全部缺失却显示为"有分数"（编造）→ 透明窗骗人。
3. trace 空却渲染出"命中路径" → 黑盒答案变相回归。

## 边界（明确不做，留后续）

- **多轮对话演进 + 历史越远越浅**：需要前端交互，留到 S4 有 UI 后；本切片只渲染单次检索。
- **图谱全局可视化**：S4。
