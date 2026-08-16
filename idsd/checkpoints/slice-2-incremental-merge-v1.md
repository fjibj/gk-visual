# 检查点：slice-2-incremental-merge v1

> 日期：2026-08-16 · 状态：构建 + 评估完成，待用户验收
> 关闭总体失败条件 1（重建整库）与 4（实体对齐失败）

## 交付了什么

在 S1 的 `graphkb` 包上增量扩展，无新前端/HTTP：

| 改动 | 说明 |
|------|------|
| `ingest.py` | `ingest_document` 摄入前快照、摄入后 diff，返回 `new_entities`（本次新增）+ `lost_entities`（增量丢失，正常为空） |
| `merge.py`（新） | 封装 `rag.amerge_entities`（SDK 核心方法，不碰 HTTP），返回 `deleted_entities` / `relationships_transferred` / `target_final` / `sources_remaining`（半合并检测，正常为空） |
| `cli.py` | `ingest` 打印新增/丢失；新增 `merge <源...> --into <目标>` 命令 |

## 关键设计决策（已与你确认）

- **自动对齐（同名）**：复用 LightRAG 的 `entity_name` 聚合，不重写。
- **显式对齐（变体）**：靠人一条 `merge` 命令；**不做自动猜合并**（那是新增"规则族"，误合并比漏合并危险，违背规则预算 ≤ 1）。
- **透明 = 正常与异常都可看见**：`new_entities`/`transferred` 报正常，`lost_entities`/`sources_remaining` 报异常，四者都是 diff 的自然延伸，无新规则族。

## 怎么验证的

1. **pytest**：15 个确定性测试（新增 diff 逻辑、merge 封装、重建/半合并检测）。
2. **Holdout**：`slice-2-v1` 判卷 **7/7**（3 成功 / 2 失败 / 2 边界）。关键实证：
   - 同名"字节跳动"跨批次只出现 1 个节点（自动对齐可靠）；
   - merge 不存在的实体 → 得体 `raise`、图不变。
3. **真实 smoke**（真实 LLM + bge-m3）：doc1→7 实体、doc2→8 实体（`new=['李四']`），doc1 实体全保留；`ByteDance` 并入"字节跳动"成功。

## 诚实交代的缺口 / 风险

1. **自动对齐依赖 LLM 抽名完全一致**：LLM 把同一实体抽成"字节跳动" vs "字节跳动公司"时不会自动合并——这正是变体显式 merge 的补口（已定）。
2. **`lost_entities`/`sources_remaining` 是防御性检测**：LightRAG 已实证正确（正常恒为空），它们只为"未来 LightRAG 行为变化"兜底，正常使用不触发。
3. **逐项余弦相似度分数**：仍留 S3（S1 已定）。
4. **`merge` 的转移关系数**是"目标实体合并前后关系差集"（我们自算），非 LightRAG 返回字段（SDK 只返回 `entity_name/source_id/graph_data`）。

## 验收前可自测

```bash
python -m pytest -q                                      # 15 passed
python holdout/evaluate.py slice-2-incremental-merge    # 7/7
# 增量：连续 ingest 两篇
python -m graphkb.cli ingest samples/sample1.txt
python -m graphkb.cli ingest samples/sample2.txt
# 显式合并（图上确有这两个实体时）
python -m graphkb.cli merge ByteDance --into 字节跳动
```
