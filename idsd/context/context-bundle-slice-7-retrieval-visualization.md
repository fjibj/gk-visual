# Context: slice-7-retrieval-visualization（检索可视化闭环）

> 技术查证 + 设计，供构建期代理参考。

## 技术栈

后端 `/api/query` 复用 `graphkb/query.py::query`（S1/S3/S5 已查证：`aquery_data` 返回 entities/relationships/chunks + 逐项余弦分数）。前端复用 S4 的 Cytoscape 图谱，加检索框 + 图上路径高亮 + 多轮颜色演进。

## trace 结构（前端高亮的数据源）

`query()` 返回 `QueryResult{question, answer, trace, trace_hit}`，其中 `trace`：

```json
{
  "entities": [{"name","type","description","score"}],
  "relationships": [{"src","tgt","description","keywords","weight","score"}],
  "chunks": [{"content","chunk_id"}]
}
```

前端高亮只需 `entities[].name` 和 `relationships[].{src,tgt}`。

## 设计决策（已拍板）

1. **后端**：`GET /api/query?question=...` → `{answer, trace, trace_hit}`，只读、复用 `query()`。
2. **前端检索框**：工具栏输入框 + 检索按钮；提交后展示答案 + 在图谱上高亮 trace 命中项。
3. **多轮颜色演进**：前端维护轮次数组（`rounds[0]`=最新），每个命中元素记 `hitAge`（0=最新）；颜色按 hitAge 由深到浅（当前轮最深、历史越远越浅），未命中项淡化（`.dimmed` opacity 0.15）。
4. **未命中**：trace_hit=false → 显示答案「未找到」+ 图上不高亮任何项，不崩溃。

## 判卷策略

- **holdout（自动化）**：测后端 `/api/query` 端点结构（answer/trace/trace_hit 字段、未命中得体、缺参拒绝）——TestClient + mock config 全离线。
- **前端可视化**：图上高亮 + 多轮颜色靠浏览器人工 + vision 复核（同 S4，可视化不纳入 pytest/holdout 自动化）。
