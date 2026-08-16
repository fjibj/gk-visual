# 检查点：slice-1-doc-to-graph v1

> 日期：2026-08-16 · 状态：构建 + 评估完成，待用户验收

## 交付了什么

一个纯 Python 包 `graphkb`（CLI + pytest，无前端/无 HTTP 服务）：

| 模块 | 职责 |
|------|------|
| `config.py` | LLM/embedding 独立可配置（`anthropic` / `openai_compat` / `ollama` / `mock`），env 优先 |
| `providers/` | 四个 provider 工厂，注入 LightRAG 的 `llm_model_func` / `embedding_func` |
| `rag.py` | LightRAG 构建 + `initialize_storages` |
| `ingest.py` | 单篇文档 → 图，返回实体/关系计数 |
| `query.py` | 检索问答，返回 `{answer, trace, trace_hit}` |
| `cli.py` | `doctor` / `ingest <file>` / `query <question>` |

**核心成果（焊死全项目约束 2）：`query` 输出结构化 trace**——dual-level 命中的实体（名/类型/描述）、关系（src/tgt/描述/关键词/weight）、块、检索关键词（high/low）、命中计数。S3 只在其上渲染。

## 怎么验证的

1. **烟测（真实 LLM + bge-m3）**：`samples/sample1.txt` 抽出 7 实体/7 关系；`query "谁创立了字节跳动？"` 正确回答并给出 trace。
2. **pytest**：11 个确定性测试通过（config / providers / _build_trace / insert_custom_kg 计数 / ingest 键名）。
3. **Holdout 考卷**：`slice-1-v1` 判卷 **7/7**（3 成功 / 2 失败 / 2 边界），严格派生自 `expectations.md`，用 `insert_custom_kg` 注入已知图 + 显式关键词保证确定性。

## 诚实交代的缺口 / 风险

1. **trace 无逐项余弦分数**（已与用户确认 → 留 S3，对 `entities_vdb`/`relationships_vdb.query` 做薄 instrumentation 补分数，不重写检索）。
2. **跨文档增量合并 / 实体对齐**（→ S2）。
3. **"未命中"难在小图触发**：LightRAG 检索 `top_k=40` 远大于小图实体数，查询"不存在实体"也会召回全图。守卫（trace 空 → 强制返回"未找到"、绝不编造）已保证不黑盒；但真实"未命中"场景需更大图（S2+）验证。
4. **holdout 的 answer 是占位符**：考卷用 mock LLM，answer 固定为 `"mock-response"`，真实 answer 语义靠烟测（真实 LLM）保证；考卷只验"trace 非空且命中 ⊆ 图中实体"的结构性可溯源。
5. **`insert_custom_kg` 无崩溃恢复日志**（LightRAG issue #3400 已知）：仅 holdout 测试用，生产摄入走 `ainsert` 不受影响。

## 验收前可自测

```bash
python -m graphkb.cli doctor
python -m graphkb.cli ingest samples/sample1.txt
python -m graphkb.cli query "谁创立了字节跳动？"
python -m pytest -q
python holdout/evaluate.py   # 需 Ollama 运行中（bge-m3）
```
