# Holdout Set（考卷区）

> IDSD 盲考闭环的"考卷"。构建时代理不可读，评估时才由判卷机执行。

## 结构

```
holdout/
├── scenarios/          # 场景文件（构建代理不可见）
│   └── {slice-name}/
│       ├── success/    # 成功场景
│       ├── failure/    # 失败场景
│       └── boundary/   # 边界场景
├── results/            # 评估结果（每轮一个版本标签，失败轮次也要存档）
└── evaluate.py         # 判卷机（评估时运行，构建期不写）
```

## 纪律

1. **考卷隔离**：`holdout/scenarios/` 构建期物理不可见（`../.claudeignore` 屏蔽）。
2. **判卷机只读**：`evaluate.py` 评估时不改逻辑。
3. **每轮新版本标签**：`slice-1-v1`、`slice-1-v2`…，失败轮次存档作证据链。
4. **场景派生自 expectations.md**，而非实现——防止"应试式优化"。

## 当前状态

- S1 的具体场景文件 + `evaluate.py` 在 **Step 6（评估前）** 编写。
- 原因：场景断言需引用 S1 构建后的实际 CLI/输出结构；语义要求已在 `idsd/intents/slice-1-doc-to-graph/expectations.md` 冻结。
- 场景将严格从 expectations.md 派生，不回看实现。
