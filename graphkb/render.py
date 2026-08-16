"""检索透明窗渲染：把 QueryResult 渲染成可读的检索路径（单次检索）。

展示 dual-level 链条：高层关键词 → 低层实体 → 命中关系 → 依据块；
命中项带余弦分数，用「分数条」区分显著度（分数越高条越实）。
"""

from __future__ import annotations

from .query import QueryResult


def _fmt_score(score) -> str:
    if score is None:
        return "无分数"
    return f"{score:.3f}"


def _bar(score, width: int = 10) -> str:
    if score is None:
        return "·" * width
    filled = int(round(max(0.0, min(1.0, score)) * width))
    return "█" * filled + "░" * (width - filled)


def render(result: QueryResult) -> str:
    """把一次检索渲染成透明窗。"""
    trace = result.trace or {}
    lines = [f"问题：{result.question}", f"答案：{result.answer}"]

    if not result.trace_hit:
        lines.append("")
        lines.append("（未命中：图中没有命中任何实体或关系，未生成检索路径。）")
        return "\n".join(lines)

    kw = trace.get("keywords") or {}
    hl = kw.get("high_level") or []
    ll = kw.get("low_level") or []
    lines.append("")
    lines.append("── 检索关键词 ──")
    lines.append(f"  高层: {hl if hl else '（无）'}")
    lines.append(f"  低层: {ll if ll else '（无）'}")

    entities = trace.get("entities") or []
    lines.append("")
    lines.append(f"── 命中实体 ({len(entities)}) ──")
    for e in entities:
        score = e.get("score")
        name = e.get("name") or "?"
        typ = e.get("type") or ""
        desc = e.get("description") or ""
        suffix = (f"（{typ}）" if typ else "") + (f" — {desc}" if desc else "")
        lines.append(f"  {_bar(score)} {_fmt_score(score)}  {name}{suffix}")

    rels = trace.get("relationships") or []
    lines.append("")
    lines.append(f"── 命中关系 ({len(rels)}) ──")
    for r in rels:
        score = r.get("score")
        src = r.get("src") or "?"
        tgt = r.get("tgt") or "?"
        desc = r.get("description") or ""
        suffix = f"（{desc}）" if desc else ""
        lines.append(f"  {_bar(score)} {_fmt_score(score)}  {src} → {tgt}{suffix}")

    chunks = trace.get("chunks") or []
    lines.append("")
    lines.append(f"── 依据块 ({len(chunks)}) ──")
    for c in chunks:
        content = (c.get("content") or "").strip()
        if content:
            lines.append(f"  · {content}")

    return "\n".join(lines)
