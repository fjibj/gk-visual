# Context: slice-2-incremental-merge（增量合并 + 实体对齐）

> 组装时间：2026-08-16 · 前置：S1 已交付 `graphkb`（config/rag/ingest/query/cli + providers）
> 本 bundle 沉淀 S2 所需的 LightRAG 能力查证 + 实证结果，供 Step 4 规划引用。

## 1. LightRAG 增量机制（复用，已实证）

- `rag.ainsert(input)`（`lightrag.py:1762`）是 SDK 入口，内部走 `apipeline_enqueue_documents` + `apipeline_process_enqueue_documents`，**每次调用只处理新文档、merge 进现有图，不重建整库**。
- **实证 spike**（真实 LLM + bge-m3，独立临时 workdir）：
  - 摄入 `sample1.txt` → 5 实体（北京/南开大学/字节跳动/张一鸣/张三）
  - 再摄入 `sample2.txt` → 7 实体（新增 产品经理/李四）
  - doc1 的 5 个实体**全部保留**（missing=[]）→ 增量成立。

## 2. 同名实体自动对齐（复用，已实证）

- ingest 内部 `merge_nodes_and_edges`（`operate.py:3293`）用 `all_nodes[entity_name].extend(...)` 按 `entity_name` 聚合，**完全同名**的实体跨 chunk/文档自动合并为单节点。
- **实证 spike**：两次摄入后"字节跳动""北京"各仅 **1** 个节点（dupes={}）→ 同名自动去重成立。
- 这是约束 1「复用 LightRAG 对齐能力」的自动腿，S2 **不重写**。

## 3. 显式对齐 `amerge_entities`（复用点）

- 签名（`lightrag.py:6489`）：
  ```python
  async def amerge_entities(
      source_entities: list[str],     # 要合并并删除的源实体名
      target_entity: str,             # 合并后的目标实体名
      merge_strategy: dict[str, str] = None,  # 字段合并策略
      target_entity_data: dict[str, Any] = None,
  ) -> dict[str, Any]
  ```
- 行为：删除源实体 → 转移其全部关系到目标 → 合并重复关系 → 更新向量 → 保留图结构。
- `merge_strategy` 支持 `concatenate` / `keep_first` / `keep_last` / `join_unique`（按字段）。
- 这是 **SDK 核心方法**，`api/routers/graph_routes.py:676` 的 HTTP 端点只是包装它 → S2 直接调 `rag.amerge_entities`，不碰 HTTP。

## 4. 关键边界（实证推论，决定 S2 范围）

- 自动合并只对「**完全同名**」生效；LLM 抽名变体（"字节跳动" vs "字节跳动公司"）**不会**自动合并。
- 因此 S2 = **自动对齐（复用，同名）+ 显式对齐（封装 `amerge_entities`，变体由人控）**，两条腿缺一不可。
- 危险自动变体对齐（拿描述相似度猜合并）**不做**——那是新增"规则族"，违背规则预算 ≤ 1；变体对齐留给人的显式命令（也为 S4 手工编辑打底）。

## 5. 其他编辑能力（S4 备料，S2 仅记录不实现）

- `aedit_entity` / `aedit_relation`（`lightrag.py:6322` / `6375`）、`adelete_entity` / `adelete_relation` —— S4 图谱手工编辑用。

## 6. 引用

- `lightrag/lightrag.py:1762`（ainsert）、`6489`（amerge_entities）、`6322/6375`（edit）
- `lightrag/operate.py:3293`（merge_nodes_and_edges）
- `lightrag/api/routers/graph_routes.py:676`（HTTP merge 端点，仅包装）
