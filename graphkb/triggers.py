"""M5 触发器：三钩子 + 一兜底，住在 harness 状态机里（不是编排层）。

## 触发器 ≠ 判据

|  | 触发器 | 判据 |
| --- | --- | --- |
| 回答什么 | **要不要查** | **查到什么算数** |
| 能否用廉价启发式 | ✅ 能 | ❌ 不能（必须可复算） |

「阈值是运气不是判据」针对的是判据。触发器是**调度**：误触发只多花一次查询，
漏触发只是维持现状。所以这里可以便宜。分工立好：**触发器随便便宜，判据必须严格。**

## 四个口子

| 钩子 | 时机 | 锚（query 位） | 证据（task 位） |
| --- | --- | --- | --- |
| **H1 起手查** | Plan 入口 | 任务里探到的实体名；没有就用任务首句 | 任务描述 |
| **H2 卡壳查** | 报错 / 重试 | 错误信息里探到的实体名；没有就用错误首句 | 错误 + 上下文 |
| **H3 回想查** | 上下文命中图实体时 | 命中实体名 | 当前上下文 |
| **H0 显式点名** | 随时 | 点名文本里的实体名；没有就原样 | 点名文本 |

自动的只有 H1/H2/H3；H0 是**逃生口**，不占总闸（用户点名必须响应）。

## H3 的精髓：零成本探针

「似曾相识」= 当前上下文里**字面命中**图上已有的实体名。不走 embedding、不调 LLM，
命中即命中（无阈值抖动）。盲区是「语义相关但字面上不共享实体名」——那会漏查，
代价是少一次助攻而不是错误，旁边还有 H1/H2/H0 兜底。

## 总闸

自动查询上限 `K`（默认 5）。每次真正发起 `memory.search` 才扣一格；被拦下 /
探针不亮不算「查过」。触发事件一律入 `events()`，包括被拦的那些——
「这次为什么没想起」必须和「这次为什么想起」一样看得见。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

AUTONOMOUS_LIMIT = 5
"""会话内自动查询上限 K。起始经验值，不是判据；H0 不受它限制。"""

HOOK_NAMES = {
    "H0": "显式点名",
    "H1": "起手查",
    "H2": "卡壳查",
    "H3": "回想查",
}

SHORT_ANCHOR_CHARS = 80
"""没有实体可当锚时，退而取文本首句当锚；太长会把锚点稀释掉。"""

H3_SCAN_CHARS = 4000
"""H3 只扫上下文前 N 字：尾部通常是离题的闲聊，扫它只会制造误触发。"""

H3_MAX_ENTITIES = 8
"""一次最多拿几个实体当锚。多了锚点就散了（判据那侧的锚点本来就不该是一大堆）。"""


# ---------------------------------------------------------------- 总闸


@dataclass
class SessionGate:
    """会话总闸：管「查几次」。与每次调用的 `budget`（管「每次查多重」）互不替代。"""

    limit: int = AUTONOMOUS_LIMIT
    used: int = 0

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError(f"总闸 K 不能为负，收到 {self.limit}")

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)

    def take(self) -> bool:
        """取一格。取不到返回 False（不是异常——被拦下是正常路径）。"""
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


# ---------------------------------------------------------------- 实体探针


class EntityProbe:
    """图实体名探针：字符级精确匹配，O(文本长度) 量级，不建索引也能用。

    实现取巧但有效：按首字分桶，桶内按名字长度降序——这样同一位置优先吃最长的名字
    （图里同时有「张三」和「张三丰」时，命中后者而不是把前三个字切走），
    命中后跳过该名字的长度，避免重叠切片。
    """

    def __init__(self, names: list[str] | None = None, scan_chars: int = H3_SCAN_CHARS):
        self.scan_chars = scan_chars
        self._buckets: dict[str, tuple[str, ...]] = {}
        self.replace(names or [])

    # ---- 载入 ----

    def replace(self, names: list[str]) -> None:
        buckets: dict[str, list[str]] = {}
        for raw in names:
            name = str(raw or "").strip()
            if not name:
                continue
            buckets.setdefault(name[0], []).append(name)
        self._buckets = {
            ch: tuple(sorted(set(v), key=len, reverse=True)) for ch, v in buckets.items()
        }

    @property
    def size(self) -> int:
        return sum(len(v) for v in self._buckets.values())

    async def refresh(self, rag) -> int:
        """会话启动时载入一次图节点名（之后靠 `replace()` 增量维护）。"""
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        names = []
        for n in nodes:
            name = str(n.get("entity_id") or n.get("id") or "").strip()
            if name:
                names.append(name)
        self.replace(names)
        return self.size

    # ---- 匹配 ----

    def match(self, text: str, limit: int = H3_MAX_ENTITIES) -> list[str]:
        """返回按出现顺序、去重后的实体名（最多 `limit` 个）。"""
        s = str(text or "")[: self.scan_chars]
        if not s or not self._buckets or limit <= 0:
            return []
        hits: list[str] = []
        i = 0
        n = len(s)
        while i < n:
            matched = None
            for name in self._buckets.get(s[i], ()):
                if s.startswith(name, i):
                    matched = name
                    break
            if matched:
                if matched not in hits:
                    hits.append(matched)
                    if len(hits) >= limit:
                        break
                i += len(matched)
            else:
                i += 1
        return hits


# ---------------------------------------------------------------- 触发事件


@dataclass
class TriggerEvent:
    """一次触发尝试的完整记录。「没查」也要有记录，否则触发器就成了新的黑箱。"""

    hook: str
    phase: str
    anchor: str = ""
    entities: list[str] = field(default_factory=list)
    queried: bool = False
    skipped: str | None = None  # gate_exhausted | no_entity
    hit: bool | None = None
    degraded: bool | None = None
    reason: str | None = None
    gate_left: int | None = None
    exempt: bool = False
    context_tokens: int | None = None
    spill: int | None = None

    def as_dict(self) -> dict:
        return {
            "hook": self.hook,
            "hook_name": HOOK_NAMES.get(self.hook, self.hook),
            "phase": self.phase,
            "anchor": self.anchor,
            "entities": list(self.entities),
            "queried": self.queried,
            "skipped": self.skipped,
            "hit": self.hit,
            "degraded": self.degraded,
            "reason": self.reason,
            "gate_left": self.gate_left,
            "exempt": self.exempt,
            "context_tokens": self.context_tokens,
            "spill": self.spill,
        }


@dataclass
class TriggerOutcome:
    event: TriggerEvent
    result: dict | None = None

    def as_dict(self) -> dict:
        return {"trigger": self.event.as_dict(), "result": self.result}


def short_anchor(text: str, limit: int = SHORT_ANCHOR_CHARS) -> str:
    """压成一句短锚：折叠空白、取首个句子、超长截断。"""
    collapsed = " ".join(str(text or "").split())
    for sep in ("。", "！", "？", "；", "\n"):
        idx = collapsed.find(sep)
        if 0 < idx < limit:
            return collapsed[: idx + 1]
    return collapsed[:limit]


# ---------------------------------------------------------------- 引擎


class TriggerEngine:
    """harness 侧的四钩子实现。检索走注入的 `search`（生产是 `MemoryTools.search`）。

    不 import mcp：触发器是纯调度逻辑，谁承载都行（最小 Python runner / cc-weixin / 别的）。
    """

    def __init__(
        self,
        search,
        probe: EntityProbe | None = None,
        gate: SessionGate | None = None,
        budget: dict | None = None,
    ):
        self._search = search
        self.probe = probe if probe is not None else EntityProbe()
        self.gate = gate if gate is not None else SessionGate()
        self.budget = budget
        self.events: list[TriggerEvent] = []

    # ---- 四个口子 ----

    async def on_plan(self, task: str) -> TriggerOutcome:
        """H1 起手查：任务边界清晰、频率低、价值高——「开干之前先想起」。"""
        return await self._fire("H1", "plan", task, task)

    async def on_stuck(self, error: str, context: str = "") -> TriggerOutcome:
        """H2 卡壳查：价值最高——「上次这个坑是这么填的」。"""
        evidence = f"{error}\n{context}".strip() if context else str(error)
        return await self._fire("H2", "stuck", str(error), evidence)

    async def on_context(self, text: str) -> TriggerOutcome:
        """H3 回想查：只在探针命中图实体时才查，不做周期性主动扫描。"""
        return await self._fire("H3", "context", text, text, require_entity=True)

    async def on_named(self, query: str, task: str | None = None) -> TriggerOutcome:
        """H0 显式点名：逃生口，不占总闸。"""
        return await self._fire("H0", "named", query, task or query, exempt=True)

    # ---- 观测 ----

    def trace(self) -> list[dict]:
        return [e.as_dict() for e in self.events]

    def reset(self) -> None:
        """新的会话 / 新的任务段：总闸重开、事件清空（探针保留，图没变就不用重载）。"""
        self.events.clear()
        self.gate.used = 0

    # ---- 内部 ----

    async def _fire(
        self,
        hook: str,
        phase: str,
        anchor_text: str,
        evidence_text: str,
        exempt: bool = False,
        require_entity: bool = False,
    ) -> TriggerOutcome:
        entities = self.probe.match(evidence_text)
        anchor = " ".join(entities) if entities else short_anchor(anchor_text)
        event = TriggerEvent(
            hook=hook,
            phase=phase,
            anchor=anchor,
            entities=entities,
            exempt=exempt,
            gate_left=self.gate.left,
        )

        if require_entity and not entities:
            # H3 的定义就是「字面似曾相识」；没命中就不该花预算去赌向量相似度
            event.skipped = "no_entity"
            self.events.append(event)
            return TriggerOutcome(event)

        if not exempt and not self.gate.take():
            event.skipped = "gate_exhausted"
            event.gate_left = self.gate.left
            self.events.append(event)
            return TriggerOutcome(event)

        event.queried = True
        event.gate_left = self.gate.left
        try:
            result = await self._search(
                {"query": anchor, "task": evidence_text}, self.budget
            )
        except Exception as exc:  # noqa: BLE001 — 记忆查挂了不该带崩正在干的活
            logger.warning("触发查询失败 hook=%s：%s: %s", hook, type(exc).__name__, exc)
            event.reason = f"search_error:{type(exc).__name__}"
            event.hit = False
            self.events.append(event)
            return TriggerOutcome(event, None)

        event.hit = bool(result.get("answer_context"))
        event.degraded = result.get("degraded")
        event.reason = result.get("reason")
        used = (result.get("trace") or {}).get("budget_used") or {}
        event.context_tokens = used.get("context_used")
        event.spill = used.get("context_spilled")
        self.events.append(event)
        return TriggerOutcome(event, result)
