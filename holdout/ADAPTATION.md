# `holdout/evaluate.ts` 相对上游改了什么

上游：`fjibj/fangjin-skills-factory` → `idsd-harness/holdout/evaluate.ts`（v3，2026-11-20）。
本地这份是**适配 gk-visual** 的副本，不是重写。下次上游更新时，按本文件逐条对一遍就行。

## 只改了【适配区】

| 位置 | 改成了什么 | 为什么 |
|---|---|---|
| `buildApp()` | 返回一个只有 `inject()` 的鸭子对象，底下 `fetch` 到真的 uvicorn | gk-visual 是 Python + FastAPI + LightRAG，没有 Fastify 可注入。判卷机核心一行不用动 |
| 服务生命周期 | 只起一次（`spawn python -m uvicorn graphkb.server:app`），跑完 `SIGTERM` + 删临时库 | ingest 是 30 秒级操作，每个场景重启既不必要也慢 |
| `resetDatabase()` | 调 `POST /api/_test/reset`（可选带 `fixture`），并在不带夹具时断言 `nodes === 0` | 进程内清库比删库重启快；顺带把「重置是否彻底」变成硬断言（陷阱 #3） |
| `runner-config.json` | `pytest -m "not slow"` + `compileall` | 基线门禁就该是这两条 |

## 改到了核心（三处，都有理由）

| 位置 | 改动 | 为什么 | 上游可以考虑收敛 |
|---|---|---|---|
| `parseScenario()` | 多解析一个 `fixture` 字段 | 手册 §3.4 建议的扩展；没有它每个场景都得自己灌文档 | 是 |
| 主循环 / `runPropertyOnce()` | 每场景、每次 property 迭代前 `resetDatabase(fixture)` | 同上 | 是 |
| `matchOp()` | `const arg = substitute(spec[op], ctx)` 取代 `spec[op]` | 手册 §6.3 的一行修复：上游只对 `$eq/$ne` 做了变量替换，`{"$lte":"{{budget}}"}` 永远拿不到值、永远失败 | 是（建议直接提回上游） |

## 没有改的

`runCheck()` / `runChecks()` / 匹配器语义 / property 生成器 / shrink / `--affected` /
`--stamp` / 退出码 / 结果落盘格式 —— 全部原样。

## 一个需要注意的地方

`main()` 在 `buildApp()` **之前**调一次 `resetDatabase()`，此时服务还没起来。
本地实现里这一步是空操作（临时库目录本来就是空的），真正的一次 `reset` 发生在
第一个场景开始前。改这块时要保住这个顺序假设。
