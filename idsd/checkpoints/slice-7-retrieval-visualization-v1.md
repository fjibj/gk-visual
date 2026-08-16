# Checkpoint: slice-7-retrieval-visualization v1

> 2026-08-17 · 检索可视化闭环（前端检索框 + 图上路径高亮 + 多轮颜色演进）。

## 完成情况

1. **后端**：`server.py` 加 `GET /api/query?question=...`，复用 `graphkb/query.py::query`，返回 `{answer, trace, trace_hit}`（只读）。
2. **前端**：工具栏检索框 + 检索按钮；提交后把 trace 命中实体/关系在图谱上高亮（未命中项淡化）；连续多轮叠加，当前轮最深、历史逐轮变浅（`hitAge` 0=最新，颜色由深红渐浅）。
3. **测试**：`tests/test_server.py` 加 2 用例（端点结构/缺参拒绝）；holdout 7 场景判卷（端点结构/未命中/只读/缺参/空问题/路由共存，TestClient 全离线）。

### 验收点覆盖

| 验收点 | 状态 | 实证 |
|--------|------|------|
| 前端检索框 | ✅ | 工具栏输入框 + 检索按钮 + Enter 提交，调 `/api/query` |
| 图上路径高亮 | ✅ | trace 命中实体/关系加 `hit` class + hitAge 着色，未命中 `.dimmed` |
| 多轮颜色演进 | ✅ | `queryRounds` 叠加，`ageColor(hitAge)` 由深到浅 |

### 判卷结果

- pytest **41 passed**（39 旧 + 2 新）。
- holdout **7/7 passed**（4 success / 1 failure / 2 boundary）。

## 诚实交代（缺口 / 风险）

1. **前端可视化靠浏览器人工验证**：图上高亮 + 多轮颜色是纯前端视觉，holdout 只覆盖后端 `/api/query` 端点结构；高亮/多轮的正确性靠浏览器 + vision 复核（同 S4，可视化不纳入自动化判卷）。
2. **多轮演进无后端状态**：轮次历史存前端内存（`queryRounds`），刷新页面即清空——符合"透明窗是展示层"定位，不引入后端规则族。
3. **颜色方案是经验值**：`ageColor` 四档（#c81e2e→#f6c5cd）为手调，未做可配置。
4. **检索依赖真实 LLM + bge-m3**：命中 + 答案生成需火山 LLM + Ollama；holdout 用 mock 只测端点结构，真实命中靠浏览器联调验证。

## 提交链

（构建 + 判卷提交，见 git log）
