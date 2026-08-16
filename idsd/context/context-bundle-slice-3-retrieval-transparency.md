# Context: slice-3-retrieval-transparency（检索路径可视化 / 透明窗渲染）

> 组装时间：2026-08-16 · 前置：S1 已产出结构化 trace（`graphkb/query.py`），S2 已交付增量+对齐。
> 本 bundle 沉淀 S3 所需的向量库 query 接口查证 + 实证，供 Step 4 规划引用。

## 1. 逐项分数的接口（复用，已实证）

- `BaseVectorStorage.query(query, top_k, query_embedding=None) -> list[dict]`（`base.py:275`）。
- nano-vectordb 实现（`kg/nano_vector_db_impl.py:414`）返回每项：
  ```python
  {**payload, "id": dp["__id__"], "distance": dp["__metrics__"], "created_at": ...}
  ```
- **实证**（真实 bge-m3 + mock LLM + `insert_custom_kg`，flush 后查询）：
  - `entities_vdb.query("字节跳动", 5)` → `[{id: "ent-…", distance: 0.8039, entity_name: "字节跳动", …}, …]`
  - `relationships_vdb.query("谁在字节跳动工作", 5)` → `[{id: "rel-…", distance: 0.6717, src_id: …, tgt_id: …, …}, …]`

## 2. 实证关键结论

1. **`distance` 是余弦相似度，值域 0~1**，越高越相似（查询"字节跳动"时"字节跳动"0.80 > "北京"0.43 > "张三"0.30）。
2. **`distance` 是 numpy `float32`**，序列化/存 trace 前须 `float()` 转换。
3. **实体结果带 `entity_name`**；**关系结果带 `src_id`/`tgt_id`，且是规范化（sorted）顺序**——原"张三→字节跳动"在向量库里存成"字节跳动→张三"。映射分数时关系的 key 须用 `tuple(sorted((src, tgt)))`。
4. 向量库 payload 的 `description`/`entity_type` 在 `insert_custom_kg` 注入下为 `null`（未存），但**不影响**：trace 的实体描述来自 `aquery_data` 的图数据，分数只需 `entity_name`/`src-tgt` + `distance` 两个源合并。

## 3. 设计含义（薄 instrumentation，不重写检索）

- 逐项分数 = 对 `entities_vdb.query` / `relationships_vdb.query` 各调一次，用 `entity_name`（实体）或 `sorted(src,tgt)`（关系）做 key，把 `distance` 填回 trace 的命中项。
- 诚实降级：向量库查询抛异常 / 查不到 → 该项 `score = None`（标注"无分数"），**绝不编造**。
- 这是"给检索器加透明窗"的补分，不碰 LightRAG 检索路径本身（约束 2）。

## 4. 渲染形态（纯 Python，S4 才加 TS 前端）

- CLI 富文本（ANSI 颜色 + 层级树），单次检索：`高层关键词 → 低层实体 → 命中关系 → 依据块`，命中项带分数、按分数区分显著度。
- 多轮对话演进 + 历史变浅留 S4+（需前端交互），本切片明确不做。

## 5. 引用

- `lightrag/base.py:275`（BaseVectorStorage.query）
- `lightrag/kg/nano_vector_db_impl.py:414`（nano query 返回结构）
- `graphkb/query.py`（S1 trace 数据源）
