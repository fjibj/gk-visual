"""M5 触发器：四钩子触发条件、总闸计数、H0 豁免、探针命中（全离线）。"""

from __future__ import annotations

import asyncio

import pytest

from graphkb.triggers import (
    AUTONOMOUS_LIMIT,
    EntityProbe,
    SessionGate,
    TriggerEngine,
    short_anchor,
)

NAMES = ["张三", "北京", "字节跳动"]


class _Search:
    """假 search：记录每次调用，可设成空结果 / 炸掉 / 带预算。"""

    def __init__(self, answer_context="[anchor] 张三（person）：工程师", boom=False):
        self.answer_context = answer_context
        self.boom = boom
        self.calls: list[tuple[dict, dict | None]] = []

    async def __call__(self, context, budget=None):
        self.calls.append((context, budget))
        if self.boom:
            raise RuntimeError("检索炸了")
        return {
            "answer_context": self.answer_context,
            "degraded": False,
            "reason": None,
            "trace": {"budget_used": {"context_used": 12, "context_spilled": 1}},
        }


def _engine(search=None, names=None, gate=None, budget=None):
    search = search or _Search()
    engine = TriggerEngine(
        search=search,
        probe=EntityProbe(NAMES if names is None else names),
        gate=gate,
        budget=budget,
    )
    return engine, search


# ---------------------------------------------------------------- 探针


def test_probe_prefers_longest_name_at_same_position():
    """图里同时有「张三」和「张三丰」时，不能把张三丰切成张三。"""
    probe = EntityProbe(["张三", "张三丰", "北京"])
    assert probe.match("张三丰在北京") == ["张三丰", "北京"]


def test_probe_skips_overlap_and_dedupes():
    probe = EntityProbe(NAMES)
    assert probe.match("张三在北京，张三又去了北京") == ["张三", "北京"]


def test_probe_no_match_returns_empty():
    probe = EntityProbe(NAMES)
    assert probe.match("今天天气不错") == []
    assert probe.match("") == []


def test_probe_respects_limit():
    probe = EntityProbe(NAMES)
    assert probe.match("张三在北京的字节跳动", limit=1) == ["张三"]


def test_probe_scan_window_cuts_tail():
    """H3 只扫前 N 字：尾部往往是离题闲聊，扫它只会制造误触发。"""
    probe = EntityProbe(NAMES, scan_chars=5)
    assert probe.match("今天天气不错张三在北京") == []


def test_probe_refresh_loads_names_from_graph():
    class _Graph:
        async def get_all_nodes(self):
            return [{"entity_id": "张三"}, {"id": "北京"}, {"entity_id": ""}, {"nope": 1}]

    class _Rag:
        chunk_entity_relation_graph = _Graph()

    probe = EntityProbe()
    assert asyncio.run(probe.refresh(_Rag())) == 2
    assert probe.match("张三在北京") == ["张三", "北京"]


# ---------------------------------------------------------------- 总闸


def test_gate_allows_k_then_blocks():
    gate = SessionGate(2)
    assert gate.take() is True
    assert gate.take() is True
    assert gate.take() is False
    assert gate.left == 0


def test_gate_rejects_negative_limit():
    with pytest.raises(ValueError, match="总闸"):
        SessionGate(-1)


def test_gate_exhaustion_blocks_automatic_hooks():
    gate = SessionGate(1)
    engine, search = _engine(gate=gate)
    first = asyncio.run(engine.on_plan("帮张三整理周报"))
    second = asyncio.run(engine.on_plan("帮张三再整理一次"))
    assert first.event.queried is True
    assert second.event.queried is False
    assert second.event.skipped == "gate_exhausted"
    assert len(search.calls) == 1, "被总闸拦下时不该真去查"


def test_h0_is_exempt_from_gate():
    """H0 是逃生口：用户点名必须响应，总闸不能把人的话憋回去。"""
    gate = SessionGate(0)
    engine, search = _engine(gate=gate)
    out = asyncio.run(engine.on_named("张三在哪工作"))
    assert out.event.queried is True
    assert out.event.exempt is True
    assert gate.used == 0
    assert len(search.calls) == 1


def test_reset_reopens_gate_and_clears_events():
    gate = SessionGate(1)
    engine, _ = _engine(gate=gate)
    asyncio.run(engine.on_plan("张三的周报"))
    engine.reset()
    assert engine.trace() == []
    assert gate.left == 1


# ---------------------------------------------------------------- 四钩子


def test_h1_fires_with_entity_anchor():
    engine, search = _engine()
    out = asyncio.run(engine.on_plan("帮张三整理周报，顺便看看北京那边的情况"))
    assert out.event.queried is True
    assert out.event.entities == ["张三", "北京"]
    assert out.event.anchor == "张三 北京"
    context, _ = search.calls[0]
    assert context["query"] == "张三 北京"
    assert context["task"] == "帮张三整理周报，顺便看看北京那边的情况"
    assert out.event.gate_left == AUTONOMOUS_LIMIT - 1


def test_h1_without_entity_still_queries_with_short_anchor():
    """H1 是状态触发（Plan 入口），没有实体也要查——锚点退化成任务首句。"""
    engine, search = _engine()
    task = "把上周的会议记录整理成一份周报。语气要正式。"
    out = asyncio.run(engine.on_plan(task))
    assert out.event.queried is True
    assert out.event.entities == []
    assert out.event.anchor == "把上周的会议记录整理成一份周报。"
    assert search.calls[0][0]["query"] == out.event.anchor


def test_h2_anchor_uses_error_entities():
    engine, search = _engine()
    out = asyncio.run(engine.on_stuck("KeyError: 张三 的字段缺失", "刚才在读写字节跳动那条记录"))
    assert out.event.entities == ["张三", "字节跳动"]
    context, _ = search.calls[0]
    assert context["query"] == "张三 字节跳动"
    assert "KeyError" in context["task"]


def test_h3_skips_when_no_entity_and_spends_no_gate():
    """H3 的定义就是「字面似曾相识」：没命中就不该花预算去赌向量相似度。"""
    gate = SessionGate(5)
    engine, search = _engine(gate=gate)
    out = asyncio.run(engine.on_context("今天天气不错，适合出去走走"))
    assert out.event.skipped == "no_entity"
    assert out.event.queried is False
    assert gate.used == 0
    assert search.calls == []


def test_h3_queries_when_entity_hit():
    engine, search = _engine()
    out = asyncio.run(engine.on_context("刚才那张表里张三的入职日期对不上"))
    assert out.event.queried is True
    assert out.event.entities == ["张三"]
    assert search.calls[0][0]["query"] == "张三"


def test_events_record_hit_budget_and_gate():
    engine, _ = _engine()
    out = asyncio.run(engine.on_plan("张三的周报"))
    event = out.event.as_dict()
    assert event["hook"] == "H1"
    assert event["hook_name"] == "起手查"
    assert event["hit"] is True
    assert event["context_tokens"] == 12
    assert event["spill"] == 1
    assert event["degraded"] is False
    assert engine.trace()[-1] == event


def test_empty_result_is_recorded_as_no_hit():
    engine, _ = _engine(search=_Search(answer_context=""))
    out = asyncio.run(engine.on_plan("张三的周报"))
    assert out.event.hit is False
    assert out.result is not None


def test_search_error_does_not_break_the_task():
    """记忆查挂了不该带崩正在干的活：记一笔、当作没捞到。"""
    engine, _ = _engine(search=_Search(boom=True))
    out = asyncio.run(engine.on_plan("张三的周报"))
    assert out.result is None
    assert out.event.hit is False
    assert str(out.event.reason).startswith("search_error")
    assert engine.trace()[-1]["queried"] is True


def test_budget_is_passed_through():
    engine, search = _engine(budget={"max_context_tokens": 100})
    asyncio.run(engine.on_plan("张三的周报"))
    assert search.calls[0][1] == {"max_context_tokens": 100}


# ---------------------------------------------------------------- 锚文本


def test_short_anchor_takes_first_sentence():
    assert short_anchor("第一句在这里。第二句不该进锚。") == "第一句在这里。"


def test_short_anchor_truncates_long_text():
    text = "啊" * 200
    assert len(short_anchor(text)) == 80


def test_config_reads_trigger_gate_from_env(monkeypatch):
    from graphkb.config import load_config

    monkeypatch.setenv("GKB_TRIGGER_K", "9")
    assert load_config().triggers.autonomous_limit == 9
