# Intent: slice-4-graph-edit（图谱可视化 + 手工编辑）

> 本切片是总体意图 Goal 3 的落地，也是**第一片引入 TS 前端**的切片。
> 前置：S1 已构图可检索、S2 已增量+对齐、S3 已透明窗渲染。
> 范围：**看整张图 + 手改节点/边 + 改动落库**。编辑回路（编辑→检索随之变化）是 S5，本切片明确不做。

## Goal

让用户能在一个页面上看到整张知识图谱，并手工修改节点/边，改动真实落库（复用 LightRAG 编辑 API）。

三个验收点：

1. **可视化**：前端把整张图渲染出来（节点 = 实体，边 = 关系），能看到实体名/类型/关系描述；
2. **编辑**：手工增删改实体/关系、合并实体，操作落到 LightRAG 图（复用其 `acreate_*` / `aedit_*` / `adelete_by_*` / `amerge_entities`）；
3. **落库可验证**：编辑后重新读图，改动确实生效（不只是在界面假改）。

## Constraints

1. **复用 LightRAG 编辑 API**：编辑落库走 LightRAG 现成的 `acreate_entity/acreate_relation/aedit_entity/aedit_relation/adelete_by_entity/adelete_by_relation/amerge_entities`，不重写图存储。
2. **后端 Python + 前端 TS**：后端 FastAPI（进程内 `import lightrag`，托管静态文件 + 提供 JSON API）；前端纯 TS + Vite + Cytoscape.js（图渲染/交互），**Node 仅构建期依赖**，产物是静态文件由 Python 托管。
3. **规则预算 ≤ 1**：编辑是"人控操作"（用户点哪改哪），不新增自动规则族。

## Failure Conditions

1. 编辑操作没落库（界面改了、重新读图却没变）→ 编辑失败。
2. 页面看不到图或改动 → 可视化失败。
3. 编辑破坏图（如删实体后残留孤儿关系、合并后丢关系）→ 编辑不安全。

## 边界（明确不做，留 S5）

- **编辑回路**：编辑后检索结果随之变化 → S5。
- **多轮对话检索可视化**：S3 已定留 UI，本切片若有余力可顺带，但非验收项。
