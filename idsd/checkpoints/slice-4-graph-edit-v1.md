# Checkpoint: slice-4-graph-edit v1

> 2026-08-16 · 图谱可视化 + 手工编辑 · 第一片引入 HTTP 服务 + TS 前端。

## 完成情况

四子切片全部落地：

1. **后端 HTTP API**（`graphkb/server.py`）：FastAPI 图 CRUD（读图/建/改/删实体与关系/合并），复用 LightRAG 编辑 API，托管 `frontend/dist` 静态文件。
2. **前端图渲染**（`frontend/`）：Vite + TS + Cytoscape.js，拉 `/api/graph` 渲染节点/边（节点按 type 着色、中文名标签）。
3. **编辑交互 + 联调**：点选节点/边 → 详情面板编辑/删除；新建实体/关系、合并实体；一个 Python 进程跑通前后端。
4. **pytest + holdout**：`tests/test_server.py` 10 用例锁定编辑落库；holdout 7 场景判卷。

### 验收点覆盖

| 验收点 | 状态 | 实证 |
|--------|------|------|
| 可视化：整图渲染 | ✅ | 浏览器实测 9 节点/10 边，中文名标签清晰（vision 复核） |
| 编辑：增删改+合并落库 | ✅ | pytest 31 passed；前端新建实体闭环（9→10 节点）实测 |
| 落库可验证 | ✅ | holdout 7/7（改后重读图生效） |

### 关键实证

- **编辑即落盘**：spike 证实 LightRAG `aedit_entity` 即时写盘（不 finalize 重启也可见），故 server 无需每操作 finalize。
- **删除连带清理**：`adelete_by_entity` 删实体时连带关系清理（b2 场景：孤儿边为空）。

## 诚实交代（缺口 / 风险）

1. **前端布局重叠**：cose 力导向在小图/密集图下标签会重叠（vision 复核发现）。功能正常，属美观优化，未处理（可后加 `--spread` 或换布局）。
2. **编辑依赖 embedding**：编辑操作会 re-embed 实体进向量库，需本地 Ollama（bge-m3）运行。Ollama 未起时编辑会失败（真实依赖，非缺陷）。
3. **可视化无自动化判卷**：holdout 判卷机只覆盖编辑落库（API 层，全 mock 离线）；前端可视化是浏览器人工验证（vision 复核截图），未纳入 pytest/holdout 自动化。
4. **编辑回路是 S5**：编辑后检索结果随之变化 → 留 S5（本切片明确不做）。
5. **TestClient deprecation warning**：starlette 提示 httpx→httpx2 迁移，仅警告，不影响功能。
6. **cose 布局参数**：`nodeRepulsion=6000` / `idealEdgeLength=100` 为经验值，未按图规模自适应。

## 提交链

`56bf0d8`(ICE) → `95bd7ab`(①后端) → `0349572`(②③前端) → `ac2a418`(④测试) → `holdout/status`(Step5/6)
