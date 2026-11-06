"""M6 端到端 demo：干活 → 自动存记忆 → 下次开工自动想起 → 注入有预算、过程可审计。

跑法（读写都在同一个 workspace，默认在临时目录里另起一个干净的库）：

    python scripts/demo_agent_memory.py                 # 只跑读侧（不花 LLM，借已有图）
    python scripts/demo_agent_memory.py --ingest        # 连写侧一起跑（会真调一次抽取）
    python scripts/demo_agent_memory.py --workspace data --ingest

读侧五步（不花 LLM）：
  1. 起手：H1 抬在任务描述上 —— 探到实体才查
  2. 埋坑：H2 抬在报错信息上
  3. 回想：H3 抬在随手写的一段上下文上（探针不亮就不查，不花预算）
  4. 点名：H0 明确要查（不受总闸限制）
  5. 总闸：连抬到 K 用完，看后面自动钩子被拦下、H0 照样能查

写侧（`--ingest`）：把一段会话记录 ingest 进去，再从图上问回来——
"这次学到的，下次真能想起"。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from graphkb.config import load_config  # noqa: E402
from graphkb.memory_api import MemoryTools  # noqa: E402
from graphkb.rag import init_rag  # noqa: E402
from graphkb.triggers import EntityProbe, SessionGate, TriggerEngine  # noqa: E402

TASK = "帮我整理张三的入职材料，顺便核对北京那边的社保"
ERROR = "KeyError: 张三 的 'join_date' 字段缺失"
OFFTOPIC = "今天天气不错，把桌面上的文件归档一下"
NAMED = "张三在哪工作"

SESSION_NOTE = """2026-11-06 复盘：张三这周把入职材料补齐了，社保由北京那边的 HR 对接。
另外确认了字节跳动的办公地点就在北京，通勤大约 40 分钟。"""


def _line(step: str, event: dict, result: dict | None) -> str:
    used = (result or {}).get("trace", {}).get("budget_used", {}) or {}
    bits = [
        f"{step:<14}",
        f"hook={event['hook']}",
        f"锚={event['anchor'][:24]!r}",
        f"实到={len(event['entities'])}",
        "查了" if event["queried"] else f"没查({event['skipped']})",
        f"捞到={'是' if event['hit'] else ('—' if event['hit'] is None else '否')}",
        f"token={event['context_tokens'] if event['context_tokens'] is not None else '—'}"
        f"/{used.get('context_tokens', '—')}",
        f"总闸余={event['gate_left']}",
    ]
    if event["degraded"]:
        bits.append(f"降级={event['reason']}")
    return "  ".join(bits)


async def main() -> int:
    parser = argparse.ArgumentParser(description="gk-visual 端到端 demo")
    parser.add_argument("--workspace", default="", help="库目录（默认临时新建一个干净库）")
    parser.add_argument("--ingest", action="store_true", help="连写侧一起跑（会真调一次 LLM 抽取）")
    parser.add_argument("--gate", type=int, default=None, help="会话总闸 K（默认读 GKB_TRIGGER_K）")
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()
    if args.workspace:
        cfg.working_dir = args.workspace
    else:
        cfg.working_dir = tempfile.mkdtemp(prefix="gkb_demo_")
    print(f"workspace : {cfg.working_dir}")
    print(f"模型      : {cfg.llm.provider}/{cfg.llm.model} | embedding {cfg.embedding.provider}/{cfg.embedding.model}")
    print()

    rag = await init_rag(cfg)
    tools = MemoryTools(cfg, rag)
    probe = EntityProbe()
    engine = TriggerEngine(
        search=tools.search,
        probe=probe,
        gate=SessionGate(args.gate if args.gate is not None else cfg.triggers.autonomous_limit),
    )
    # 会话启动就把图上的实体名载进来（探针的初始化，不是周期扫描）
    print(f"探针载入实体名 {await probe.refresh(rag)} 个")
    print()

    rows: list[str] = []
    try:
        # ---- 写侧（可选）：干活产生的记录落库 ----
        if args.ingest:
            print("[写] memory.ingest(source=session) …… 一次抽取大约几十秒")
            job = await tools.ingest(
                source="session", content=SESSION_NOTE, title="直播复盘-20261106", wait=True
            )
            print(
                f"     status={job['status']} doc_id={job['doc_id']} "
                f"entities={job['result']['entity_count']} relations={job['result']['relation_count']}"
            )
            probe_size = await probe.refresh(rag)
            print(f"     图变了，探针重载：{probe_size} 个实体名")
            print()

        # ---- 读侧：四钩子 + 总闸 ----
        steps = [
            ("① 起手 H1", await engine.on_plan(TASK)),
            ("② 埋坑 H2", await engine.on_stuck(ERROR)),
            ("③ 回想 H3", await engine.on_context("刚才那张表里张三的入职日期对不上")),
            ("④ 离题 H3", await engine.on_context(OFFTOPIC)),
            ("⑤ 点名 H0", await engine.on_named(NAMED)),
        ]
        for step, outcome in steps:
            rows.append(_line(step, outcome.event.as_dict(), outcome.result))

        # ---- 总闸压力：把剩下的格用完，再看自动钩子被拦 ----
        exhausted = None
        for _ in range(engine.gate.limit + 1):
            outcome = await engine.on_stuck(ERROR)
            if not outcome.event.queried:
                exhausted = (True, outcome)
                break
        if exhausted:
            _, outcome = exhausted
            rows.append(_line("⑥ 总闸耗尽", outcome.event.as_dict(), outcome.result))
        named_after = await engine.on_named(NAMED)
        rows.append(_line("⑦ 被拦后点名", named_after.event.as_dict(), named_after.result))

        print("=== 触发事件 ===")
        for row in rows:
            print("  " + row)
        print()

        first = steps[0][1].result or {}
        print("=== 第一次起手查注入的上下文（answer_context）===")
        print(first.get("answer_context") or "（空）")
        print()
        print("=== 它的审计面（trace，不注入）===")
        trace = first.get("trace") or {}
        print(
            json.dumps(
                {
                    "anchors": trace.get("anchors"),
                    "cited": trace.get("cited"),
                    "paths": [p.get("from") + "→" + p.get("to") for p in trace.get("paths") or []],
                    "retrieved": (trace.get("retrieved") or {}).get("entity_count"),
                    "budget_used": trace.get("budget_used"),
                    "evidence_empty": trace.get("evidence_empty"),
                },
                ensure_ascii=False,
            )
        )
        print()

        # ---- 写侧验证：刚存进去的那件事，能不能被想起来 ----
        if args.ingest:
            again = await engine.on_named("张三的入职材料后来怎么弄的？")
            print("=== 写后回想（H0 点名同一件事）===")
            print("  " + _line("⑧ 写后 H0", again.event.as_dict(), again.result))
            ctx = (again.result or {}).get("answer_context") or ""
            print("  —— 注入里有没有刚学到的内容：", "有" if "社保" in ctx else "（没提到社保，可看 spill_refs）")
            print()

        # ---- 审计：每个事件都在 engine.trace() 里 ----
        print(f"=== 本次会话共 {len(engine.events)} 条触发记录（含被拦下的）===")
        for e in engine.trace():
            print(f"  {e['hook']} {e['phase']:<8} 查={e['queried']} 跳过={e['skipped']} 总闸余={e['gate_left']}")
    finally:
        await rag.finalize_storages()

    print()
    print("demo OK")
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
