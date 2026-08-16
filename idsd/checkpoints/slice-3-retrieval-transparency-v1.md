# 检查点：slice-3-retrieval-transparency v1

> 日期：2026-08-16 · 状态：构建 + 评估完成，待用户验收
> 关闭总体失败条件 2（检索路径黑盒，看不到"凭什么"）

## 交付了什么

在 S1 的 trace 之上做渲染 + 补分数，不改检索算法：

| 改动 | 说明 |
|------|------|
| `query.py` | 加 `_score_trace`：对 `entities_vdb.query` / `relationships_vdb.query` 各调一次，用 `entity_name` / `sorted(src,tgt)` 做 key 把余弦分数填回 trace；`float32→float`；查询异常/查不到 → `score=None`（绝不编造） |
| `render.py`（新） | 把 `QueryResult` 渲染成透明窗：`高层关键词 → 低层实体 → 命中关系 → 依据块`，命中项带分数条（`█░`）区分显著度 |
| `cli.py` | `query` 默认渲染透明窗，`--json` 保留原始 trace；未命中如实显示 |

## 关键设计决策

- **逐项分数 = 薄 instrumentation**：复用向量库现成 `query` 接口，不重写检索/向量逻辑（约束 2）。
- **深度着色用分数条而非 ANSI 颜色**：`████░░` 按分数长短，纯文本跨平台（Windows 终端 ANSI 兼容不稳），同样是"按分数区分显著度"。
- **诚实降级**：分数拿不到就标"无分数"，trace 空就标"未命中"，绝不画假路径/编分数。

## 怎么验证的

1. **pytest**：21 个测试（新增 `_score_trace` 映射、`_safe_score`、`render` 命中/未命中/无分数）。
2. **Holdout**：`slice-3-v1` 判卷 **7/7**（3 成功 / 2 失败 / 2 边界）。
3. **真实 smoke**（真实 LLM + bge-m3）：`query "谁创立了字节跳动？"` 渲染出 9 实体 + 10 关系，多数带分数（0.20~0.72），两个低相关关系如实标"无分数"。

## 诚实交代的缺口 / 风险

1. **逐项分数的 top_k 限制**：`top_k = 命中数`，当向量库 top-k 排序与 dual-level 命中列表不完全对齐时，个别命中项可能拿不到分数（标 `None`/"无分数"）。这是"薄 instrumentation"的固有 tradeoff，已由 expectations boundary 定义为合法降级；真实 9 实体场景分数齐全。
2. **"深度着色"未用真颜色**：用分数条（`█░`）替代 ANSI 色，跨平台更稳，但视觉上不如彩色鲜艳（可后续加 `--color`）。
3. **多轮对话演进 + 历史变浅**：留 S4（需前端交互，已与你确认）。
4. **逐项分数是"补查"**：在 `aquery_data` 之外额外查一次向量库，多两次 embedding（实体+关系）开销——只为透明，不参与答案生成。

## 验收前可自测

```bash
python -m pytest -q                                     # 21 passed
python holdout/evaluate.py slice-3-retrieval-transparency   # 7/7
python -m graphkb.cli query "谁创立了字节跳动？"        # 透明窗渲染
python -m graphkb.cli query "谁创立了字节跳动？" --json # 原始 JSON trace（含 score）
```
