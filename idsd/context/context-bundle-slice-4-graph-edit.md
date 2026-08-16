# Context: slice-4-graph-edit（图谱可视化 + 手工编辑）

> 组装时间：2026-08-16 · 前置：S1–S3 已交付构图/增量对齐/透明窗。
> 本 bundle 沉淀 S4 所需的 LightRAG 编辑 API 查证 + 技术选型，供 Step 4 规划引用。

## 1. LightRAG 编辑 API（复用，已查证）

落库能力**完全复用** LightRAG，不重写图存储（约束 1）：

| 操作 | SDK 方法（`lightrag.py`） | 入参 |
|------|---------------------------|------|
| 创建实体 | `acreate_entity` | `entity_name, entity_data{description, entity_type}` |
| 创建关系 | `acreate_relation` | `source_entity, target_entity, relation_data{description, keywords}` |
| 编辑实体 | `aedit_entity` | `entity_name, updated_data, allow_rename=True, allow_merge=False` |
| 编辑关系 | `aedit_relation` | `source_entity, target_entity, updated_data` |
| 删除实体 | `adelete_by_entity` | `entity_name`（连带其关系） |
| 删除关系 | `adelete_by_relation` | `source_entity, target_entity` |
| 合并实体 | `amerge_entities` | `source_entities, target_entity`（S2 已封装 `graphkb/merge.py`） |

读图接口：`rag.chunk_entity_relation_graph.get_all_nodes()` / `get_all_edges()`（S1 已用，节点键 `entity_id`、边键 `source`/`target`）。

## 2. 技术选型（待用户拍板）

- **后端**：FastAPI + uvicorn（进程内 `import lightrag`，托管静态前端 + 提供 JSON API；自动 `/docs` 便于调试）。
- **前端**：纯 TS + **Vite**（构建）+ **Cytoscape.js**（图渲染/交互/编辑，成熟稳定）；不引入 React/Vue 框架，保持轻量、便于打包发布。
- **产物**：Vite 构建成静态文件，由 FastAPI 托管 → 一个 Python 进程跑通前后端。

## 3. 环境实况

- node v24.17.0、npm 11.13.0 已就绪（前端构建可用）。
- fastapi / uvicorn **未装**（构建期装，走清华 pip 镜像）。
- npm 依赖（vite/cytoscape）需联网装，用户在中国网络，必要时走 npmmirror 镜像。

## 4. 引用

- `lightrag/lightrag.py:6322`（aedit_entity）、`6375`（aedit_relation）、`6161`（adelete_by_entity）、`6197`（adelete_by_relation）、`6489`（amerge_entities）、`acreate_entity/acreate_relation`（同区）
- `graphkb/merge.py`（S2 已封装 amerge_entities）
