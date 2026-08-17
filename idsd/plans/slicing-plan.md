# 切片计划（Slicing Plan）

> 从总体意图 `idsd/intents/overall/intent.md` 切出的 5 个薄切片。
> 每个切片走一次 planned-build 完整 ICE 闭环，可独立验证。

## 已定架构（2026-08-16）

- **后端**：Python，进程内 `import lightrag`（复用 LightRAG 的构图 / 增量 / 去重 / dual-level 检索）。
- **前端**：TypeScript，S4 起引入，编译成静态文件由 Python 后端托管（Node 仅构建期依赖）。
- **LLM/embedding 可配置**：provider 抽象，三类（openai_compat / anthropic / ollama），LLM 与 embedding 独立配置。
- **理由**：约束 1 锁死 LightRAG（Python）；后端与其同进程 → 一个运行时、少一层 HTTP、可直接注入检索 trace。
- **S1–S3 纯 Python**（CLI + 测试验证，无 HTTP 服务）；**S4 起加 TS 前端**。

## 切片清单

| # | 切片 | 一句话目标 | 依赖 | 关掉哪条失败条件 |
|---|------|-----------|------|------------------|
| S1 | slice-1-doc-to-graph | 单篇文档 → 图 + 可检索，检索输出结构化 trace | — | — |
| S2 | slice-2-incremental-merge | 第二篇并入，同实体去重合并，不重建整库 | S1 | 失败条件 1、4 |
| S3 | slice-3-retrieval-transparency | 透明窗渲染 + 解释（深度着色、历史越远越浅） | S1、S2 | 失败条件 2 |
| S4 | slice-4-graph-edit | 图谱可视化 + 手工编辑节点/边并落库 | S1 | — |
| S5 | slice-5-edit-loop | 手工编辑后检索结果随之变化（闭环） | S1、S3、S4 | 失败条件 3 |
| S6 | slice-6-document-lifecycle | 文档生命周期闭环：上传→图、列表、删除→图收敛 | S1、S4 | —（补全文档入口；删除后检索随动复用 S5 闭环） |
| S7 | slice-7-retrieval-visualization | 检索可视化闭环：前端检索框 + 图上路径高亮 + 多轮颜色演进 | S1、S3、S4、S5 | 失败条件 2 |
| S8 | slice-8-document-ingestion-enhancement | 文档摄取增强：文件格式（docx/xlsx/pptx/pdf）+ URL 抓取 → 复用 S6 管线 | S6 | —（摄取入口扩展；属性保持现状） |

## 执行顺序

```
S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8
```

## 已拍板的 tradeoff

- **A**：5 薄片（不合并）。理由：5 条失败条件两两正交，厚片无法归因；S2 复用 LightRAG 现成能力，薄片成本低但隔离价值高。
- **B**：选 B2（S1→S2→S3），**且 S1 焊死 trace 暴露口**。理由：先验正确性（对齐）后验差异化（透明）；trace 机制在 S1 就落，S3 只做渲染。
- **C**：S4 / S5 拆开。理由：失败条件 3 是"聚合边界"类 bug（图改了、检索没变），必须单独一张考卷。

## 检查点（checkpoint）

- S1 完成 → 人工确认 trace 暴露口 + 构图可检索
- S2 完成 → 人工确认增量合并/去重对齐（正确性地基）
- S3 完成 → 人工确认透明窗渲染
- S4 完成 → 人工确认图谱可视化 + 手工编辑
- S5 完成 → 人工验收编辑回路闭环
- S6 完成 → 人工确认上传→图、文档列表、删除→图收敛
- S7 完成 → 人工确认检索框 + 图上路径高亮 + 多轮颜色演进
- S8 完成 → 人工确认文件格式解析 → 图、解析失败得体（URL 抓取后置）

## 未开工切片的占位（完整 ICE 待各自切片开工时再写）

- S2：增量合并 + 实体对齐（占位）
- S3：检索路径可视化（占位）
- S4：图谱可视化 + 手工编辑（占位）
- S5：编辑回路（占位）
- S6：文档生命周期闭环（占位）
- S7：检索可视化闭环（占位）
- S8：文档摄取增强（占位）
