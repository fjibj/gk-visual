# Context Bundle: slice-1-doc-to-graph

> 组装日期：2026-08-16。供 S1 构建使用。

## 项目概览

个人知识库，核心诉求是"透明 + 可编辑"：文档如何变图、检索走了哪条路径、人能否改图、编辑是否影响检索。总体意图见 `idsd/intents/overall/intent.md`。

## 技术栈与架构（已定稿）

- **后端**：Python，进程内 `import lightrag`（约束 1 锁死 LightRAG，它是 Python-only）。
- **前端**：TypeScript，S4 起引入，静态托管（Node 仅构建期依赖）。
- **S1–S3 纯 Python + CLI + pytest**，无 HTTP 服务、无前端。

## LightRAG SDK 关键事实（已查证，来源：官方 README + ProgramingWithCore.md）

### 初始化（必须两步）
```python
rag = LightRAG(working_dir=..., llm_model_func=..., embedding_func=...)
await rag.initialize_storages()   # 漏掉会报 AttributeError: __aenter__
```

### 摄入
- `rag.insert("text")` / `await rag.ainsert("text")`
- 支持 `ids=[...]`（文档 ID）、`file_paths=[...]`（引用溯源）。
- 批量 `rag.insert(["t1","t2"], ids=[...])`；`max_parallel_insert`（默认 3）。

### 检索（QueryParam）
- `rag.query(q, param=QueryParam(...))` / `await rag.aquery(...)`
- `mode`：`local`（实体精准匹配）/ `global`（关系链/宏观主题）/ `hybrid` / `naive`（纯向量）/ `mix`（默认，全合并）/ `bypass`。
- `top_k`：local 模式下=实体数，global 模式下=关系数。
- **`only_need_context=True`**：只返回检索到的上下文（实体/关系/文本块），**不生成答案** —— 这是 S1 trace 暴露口的候选机制。
- `only_need_prompt=True`：只返回拼好的 prompt。

### trace 暴露口结论（S1 命根子）
- ✅ 已验证：**不需要重写 LightRAG 检索**，`only_need_context` 能直接拿到"检索到了什么"。
- ⚠️ 待 Step 5 验证：`only_need_context` 返回的**精确结构**（是结构化实体/关系列表，还是拼好的文本）。若要"实体/关系 + 评分"的严格结构化 trace，可能需下探到 LightRAG 内部检索函数（local 的实体检索 / global 的关系检索）做**薄 instrumentation**——这仍属"给检索器加透明窗"，不违背约束 1/2。

### 编辑能力（S4/S5 的地基，已确认现成）
- `create_entity` / `edit_entity` / `create_relation` / `edit_relation`
- `delete_by_entity` / `delete_by_relation` / `adelete_by_doc_id`
- **`merge_entities(source_entities, target_entity)`** —— S2 的去重对齐现成能力。
- 均有同步/异步（`a` 前缀）版本。

### 中文抽取
- `addon_params={"language": "Chinese"}` 或 env `SUMMARY_LANGUAGE=Chinese`，控制实体/关系命名语言。

### 存储（S1 用默认即可）
- 默认：`JsonKVStorage` + `NanoVectorDBStorage` + `NetworkXStorage` + `JsonDocStatusStorage`（内存 + 文件持久化），适合开发调试。

## Provider 抽象（可配置 LLM/embedding，设计定稿）

不写死某个模型。通过配置文件（YAML，env 可覆盖）选择 provider，工厂注入对应的 `llm_model_func` / `embedding_func` 到 LightRAG。**LLM 与 embedding 独立配置**（LightRAG 本就分开注入，且 embedding 常本地化）。

三类 provider：

| 类别 | 协议 | 覆盖 |
|------|------|------|
| `openai_compat` | `/v1/chat/completions` + `/v1/embeddings` | OpenAI、DeepSeek、Kimi、通义、GLM、vLLM/SGLang、LiteLLM、OpenRouter… |
| `anthropic` | Anthropic Messages API `/v1/messages` | Claude（**无 embedding**，embedding 需另配 openai_compat / ollama / voyage） |
| `ollama` | 本地 Ollama | LLM + embedding 均可 |

配置形如：

```yaml
llm:       { provider: openai_compat, base_url, api_key, model }
embedding: { provider: ollama, base_url, model, dim }
```

LightRAG 自带 `lightrag.llm.openai` / `lightrag.llm.ollama` 函数可复用；`anthropic` 需手写一个 `llm_model_func` 包 Messages API。

**残余依赖**：框架支持三类，但 S1 端到端测试仍需**一个真实可用的 provider 配置**（用户提供其一即可；无 key 时可用 mock provider 搭骨架 + 跑确定性测试）。

## 本切片 Intent 摘要

见 `idsd/intents/slice-1-doc-to-graph/intent.md`。要点：单篇文档→图；基于图回答且答案可溯源；检索输出结构化 trace（本切片只输出 JSON，不渲染）。

## 本切片 Expectations 摘要

见 `idsd/intents/slice-1-doc-to-graph/expectations.md`。3 成功 / 2 失败 / 2 边界。

## 残余风险

1. `only_need_context` 的精确返回结构未知 → 决定 trace 是"直接用"还是"打薄 instrumentation"（Step 5 第一件事验证）。
2. LLM/embedding provider 未定 → 阻塞构建。
3. expectations.md 的边界"同一实体反复提及不重复建节点"与 LightRAG 单文档内去重行为的关系待验证，可能收紧或挪到 S2。
