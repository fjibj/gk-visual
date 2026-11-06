# M4 记录：溯源标签（extracted / manual）

> 日期：2026-11-06
> 范围：`graphkb/provenance.py`（新）、`graphkb/server.py::_read_graph`、`graphkb/memory_api.py`（hits / expand）、`frontend/src/{api,main}.ts`
> 上游：backlog#9（2026-08-22 从 graphify 对比里记下的候选）；下游：M5 触发器、将来的置信度

## 1. 要解决的问题

一张个人图里混着两种东西：**从文档里抽出来的**，和**人手工敲进去的**。它们的可信度完全不同——
抽取来的可能是模型读错、合并错了；手工加的是人的断言。用户看图、agent 取上下文时，都得能分清。
graphify 那句「永远知道哪些是读到的、哪些是猜的」说的就是这个。

## 2. 关键决策：读出来的，不是记出来的

候选方案：

| 方案 | 做法 | 代价 |
|---|---|---|
| A. 旁挂账本 | 自己维护一份 `{name: origin}` 落盘 | 与图会漂移：删/改/合并实体时账本得跟着动，一旦漏了，两处各说一套 |
| B. **从 `source_id` 读**（采用） | 用 LightRAG 自己留下的痕反推 | 零存储、零迁移、永不漂移；代价是只能区分到「有没有人碰过」 |

采用 B 的直接原因是读到了 LightRAG 的实现（`utils_graph.py:1096`）：

```python
node_data = {
    ...
    "source_id": entity_data.get("source_id", "manual_creation"),   # ← 手工新建的哨兵值
    "file_path": entity_data.get("file_path", "manual_creation"),
}
```

也就是说「手工 vs 抽取」这件事 LightRAG 早就记了，只是没人读。所以我们只要反推：

| `source_id` 形状 | origin |
|---|---|
| 一串 chunk_id | `extracted` |
| `manual_creation` | `manual` |
| 两样都在（编辑过抽取实体 / 合并过手工实体） | `mixed` |
| 空 / 无字段 | `unknown` |

实测真库（17 节点 / 16 边）：`mixed` 1 个（张三——早期手工编辑过）、`extracted` 16 个。对得上。

## 3. 来源文档：为什么不信节点自己的 `file_path`

真库里 `张三.file_path = "unknown_source<SEP>manual_creation"`——早期 CLI 摄入没传 `file_path`，
节点上记的是哨兵值而不是文档名。但 `kv_store_text_chunks` 里每条 chunk 的 `full_doc_id` 都是真的。

所以来源文档一律 **批量查块存储**（`text_chunks.get_by_ids`，一次请求一次批量，不是 N+1），
节点字段只当兜底。这与 `documents._doc_entity_relation_counts` 用的是同一套依据。

块已经找不到时（文档被覆盖/删除后会这样）不装没事：计入 `unresolved`，前端明说
「另有 N 块内容已无据可查」——那正是「这部分内容已经追不回去了」的事实。

## 4. 视觉通道：为什么用底晕 + ✎，不用虚线边框

M4 计划里写的是「虚线边框/小图标」。但 **边框通道已经被 S7 的命中分层占满了**：

- 粗实线环 = 问题锚点
- 虚线环 = 答案引用 / 路径中间点

再加一个"虚线边框 = 人工"就会撞车：一个人工创建、又恰好被检索命中的节点，到底该画哪一种？
所以人工痕迹走两条新通道：

1. **标签后缀 `✎`**（语义：有人碰过），不随时间、不随命中状态消失；
2. **紫色底晕**（`underlay-*`，结构上可扫），与边框正交。

图例只在图里真的存在人工元素时出现（左上角），不做常驻装饰。

## 5. 契约

| 出口 | 字段 |
|---|---|
| `GET /api/graph` | 每个 node/edge：`origin` + `provenance{manual, docs, doc_ids, chunks, unresolved}` |
| `memory.search` | `hits.entities[i]` / `hits.relationships[i]` 同上 |
| `memory.expand` | `items[i]` 同上（entity/relation 走图记录；chunk 直接用自己的 `full_doc_id`） |

恒为四态之一，**读不到就是 `unknown`，不是 `null`**——字段恒在，调用方不用写两种分支。

## 6. 跳版本坑：1.5.7 把手工关系的 `source_id` 改成了空串

第一版只在本地（lightrag 1.5.6）全绿，CI（1.5.7）上 `test_graph_marks_manual_origin` 直接红：
手工建的实体是 `manual`，手工建的**边**却是 `unknown`。

原因：1.5.7 的 `utils_graph.acreate_relation` 把 `source_id` 默认值从 `"manual_creation"`
改成了空串（docstring 明写“An omitted source_id is stored as an empty string”），
但 `file_path` 仍写 `"manual_creation"`。只认 `source_id` 的话，同一件事在两个小版本里两种结论。

修法：`origin_of(source_id, file_path)` 两边都看——`source_id` 或 `file_path` 里出现
`manual_creation` 就算人工痕迹。加了回归用例（`test_origin_lightrag_157_manual_relation_shape`），
并把本机 lightrag 升到 1.5.7、与 CI 同版跑一遍（147 passed）。

教训：M0 已经因为 1.5.7 红过一次（`get_docs_by_status`）。**凡是把上游存储字段当契约读的地方，
就得在两个小版本上都跑一遍**——本地绿不等于 CI 绿。

## 7. 边界

- 分不出「谁、什么时候改的」；也没有「改回去」的历史。要那些得真上审计日志。
- `memory.ingest(origin="session")` 里的 origin 是**另一个维度**（记忆从哪来：doc/session/note），
  当前只回显不落库。别把它和节点 origin 混为一谈——这一点在 README 与 job warnings 里都写明了。
- 底晕在超大图上会增加渲染负担（cytoscape 每条元素多一层绘制）。个人库规模（几百节点）无感。

## 8. 测试

- `tests/test_provenance.py`（10 例）：四态判定、批量解析、顺序对齐、unresolved 计数、
  块存储炸掉不崩、`unknown_source` 回退 doc_id、按名字取（含取不到不进结果）。
- `tests/test_mcp.py`（+3 例）：命中项的 `mixed`/`manual`/`extracted`、读不到时 `unknown`、`expand` 带来源。
- `tests/test_server.py`（+1 例）：`/api/graph` 人工新建的实体/边字段完整。

pytest：118 passed（全离线）。
