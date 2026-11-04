"""Agent 记忆面的逻辑层：三个工具的实现，**不 import mcp**。

为什么单独一个模块：MCP 是适配器，不是能力。把「检索/写入/查任务」放在这里，
好处有三——测试不需要装 MCP SDK、Web 面将来也能复用、SDK 换版本只动 `mcp_server.py`。

铁律（对齐《接口设计》P1–P7）：
  P1 单一核心：search 直接调 `query()`，不新开检索分支
  P3 注入与审计分离：`answer_context`（预算内、可注入） ≠ `trace`（完整、只供审计）
  P4 预算是展示预算：超限如实截断并计数，不静默丢弃
  P5 降级要诚实：`degraded` + `reason` 一起回，让调用方自己决定信多少
  P6 溯源字段先留位：`origin` 恒为 None，等 M4 落地
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from .config import Config, RetrievalConfig
from .documents import slugify, upsert_document
from .query import query

logger = logging.getLogger(__name__)

API_VERSION = "1"

DEFAULT_MAX_CONTEXT_TOKENS = 800
"""answer_context 的默认预算（token）。断崖式调大之前先看 M3 的 Inline&Spill。"""

INGEST_SOURCES = frozenset({"doc", "session", "note"})
MODES = frozenset({"agent", "human", "auto"})

# 降级原因按「越靠前越该让调用方知道」排序：query 与 task 相同是调用方写法问题，
# 最可操作，所以排第一。
REASON_PRIORITY = ("texts_equal", "vdb_error", "no_anchor", "vector_fallback", "budget_truncated")

JOB_RETENTION = 200
"""任务表上限（进程内存）。超了就丢最老的已完成任务——job_id 本来就是短命票据。"""


# ---------------------------------------------------------------- 预算


def _int(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"预算必须是整数，收到 {value!r}") from None


@dataclass
class Budget:
    retrieval: RetrievalConfig
    max_context_tokens: int

    def as_dict(self) -> dict:
        return {
            "top_k": self.retrieval.hit_top_k,
            "max_hops": self.retrieval.max_hops,
            "max_paths": self.retrieval.max_paths,
            "context_tokens": self.max_context_tokens,
        }


def resolve_budget(raw: dict | None, default: RetrievalConfig) -> Budget:
    """`budget` 入参 → 检索预算。负值/零值一律报错：预算是上限，不允许悄悄变成 0。"""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("budget 必须是对象")
    rc = RetrievalConfig(
        hit_top_k=_int(raw.get("top_k"), default.hit_top_k),
        max_hops=_int(raw.get("max_hops"), default.max_hops),
        max_paths=_int(raw.get("max_paths"), default.max_paths),
    )
    max_ctx = _int(raw.get("max_context_tokens"), DEFAULT_MAX_CONTEXT_TOKENS)
    for name, value in (
        ("top_k", rc.hit_top_k),
        ("max_hops", rc.max_hops),
        ("max_paths", rc.max_paths),
        ("max_context_tokens", max_ctx),
    ):
        if value < 1:
            raise ValueError(f"budget.{name} 必须 ≥1，收到 {value}")
    return Budget(retrieval=rc, max_context_tokens=max_ctx)


# ---------------------------------------------------------------- answer_context


def estimate_tokens(text: str) -> int:
    """粗估 token：CJK 按 1 字 ≈ 1 token，其余按 4 字符 ≈ 1 token。

    M2 先用粗估（不为此引一个 tokenizer 依赖）；M3 改 Inline&Spill 时换成精确计数。
    粗估只会偏保守，不会让注入内容超预算太多。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk + 3) // 4


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _layer_rank(layer: str | None) -> int:
    return {"anchor": 0, "cited": 1, "path": 2, "direct": 0}.get(layer or "", 9)


def build_answer_context(
    entities: list[dict],
    relationships: list[dict],
    chunks: list[dict],
    max_tokens: int,
) -> tuple[str, int, int]:
    """把命中拼成「唯一会被注入 agent 上下文」的纯文本（零 LLM、可复算）。

    返回 (文本, 用掉的 token, 因预算被丢弃的条数)。超预算的条目**不静默丢**：
    计数会进 `budget_used.context_dropped`，并让 `reason=budget_truncated`。
    """
    items: list[str] = []
    for e in sorted(entities, key=lambda x: (_layer_rank(x.get("layer")), str(x.get("name") or ""))):
        kind = e.get("layer") or "entity"
        line = f"[{kind}] {e.get('name')}"
        if e.get("type"):
            line += f"（{e['type']}）"
        desc = _clip(e.get("description") or "", 240)
        items.append(line + (f"：{desc}" if desc else ""))

    for r in sorted(relationships, key=lambda x: _layer_rank(x.get("layer"))):
        kind = r.get("layer") or "edge"
        desc = _clip(r.get("description") or "", 240)
        items.append(
            f"[{kind}] {r.get('src')} -> {r.get('tgt')}" + (f"：{desc}" if desc else "")
        )

    for c in chunks[:3]:
        content = _clip(c.get("content") or "", 400)
        if content:
            items.append(f"[chunk] {content}")

    kept: list[str] = []
    used = 0
    dropped = 0
    for line in items:
        cost = estimate_tokens(line) + 1
        if used + cost > max_tokens:
            dropped += 1
            continue
        kept.append(line)
        used += cost
    return "\n".join(kept), used, dropped


# ---------------------------------------------------------------- 写入任务


@dataclass
class Job:
    job_id: str
    doc_id: str = ""
    origin: str = "extracted"
    status: str = "queued"  # queued | running | done | error
    progress: str = "排队中"
    error: str | None = None
    result: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "doc_id": self.doc_id,
            "origin": self.origin,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "result": self.result,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------- 工具实现


class MemoryTools:
    """`memory.*` 三个工具的落点。构造即绑定 workspace（由 MCP server 启动时决定）。"""

    def __init__(self, cfg: Config, rag):
        self.cfg = cfg
        self.rag = rag
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---- memory.search ----

    async def search(
        self,
        context: dict,
        budget: dict | None = None,
        mode: str = "agent",
        caller: str | None = None,
    ) -> dict:
        if not isinstance(context, dict):
            raise ValueError("context 必须是对象（含 task / query / anchors_hint / recent）")
        if mode not in MODES:
            raise ValueError(f"mode 只能是 {sorted(MODES)}，收到 {mode!r}")

        task = str(context.get("task") or "").strip()
        if not task:
            # 证据位不能空着跑：task 就是证据源，缺了它分层只能靠猜
            raise ValueError(
                "context.task 必填——Agent 场景用它当证据源（对应人类面的「答案」），"
                "缺了它就没有证据层"
            )
        query_text = str(context.get("query") or "").strip()
        anchor_text = query_text or task
        b = resolve_budget(budget, self.cfg.retrieval)

        if mode == "auto":
            mode = "agent" if anchor_text != task else "human"

        reasons: list[str] = []
        warnings: list[str] = []

        if mode == "agent" and anchor_text != task:
            # Agent 主路：锚点取 query，证据取 task，且不生成答案（省一次 LLM）
            result = await query(
                self.rag,
                anchor_text,
                budget=b.retrieval,
                anchor_text=anchor_text,
                evidence_text=task,
                generate_answer=False,
            )
            used_mode = "agent"
        else:
            if mode == "agent":
                reasons.append("texts_equal")
                warnings.append(
                    "context.query 缺省或与 context.task 相同：锚点与证据是同一段文本，"
                    "证据层会塌成空，所以已退回人类面语义（用生成答案当证据位）。"
                    "想要干净的 Agent 分层，请传一个更短的问题当 context.query。"
                )
            # 人类面语义：anchor=问题（或 query）、evidence=答案
            result = await query(self.rag, anchor_text, budget=b.retrieval)
            used_mode = "human"

        trace = result.trace or {}
        layers = trace.get("hit_layers") or {}
        anchor_mode = layers.get("anchor_mode")
        if anchor_mode == "vdb_error":
            reasons.append("vdb_error")
            warnings.append("向量库查询异常：本次不分层、不猜锚点，上下文原样交出（score=None）。")
        elif anchor_mode == "no_anchor":
            reasons.append("no_anchor")
            warnings.append("问题与任务文本里都没有字面实体名，也没有可用兜底锚点。")
        elif anchor_mode == "vector_fallback":
            reasons.append("vector_fallback")
            warnings.append("问题里没有字面实体名，锚点靠向量兜底选出——可靠性下降，别当强证据。")

        entities = [{**e, "origin": None} for e in trace.get("entities", [])]
        relationships = [{**r, "origin": None} for r in trace.get("relationships", [])]
        chunks = list(trace.get("chunks", []))

        if result.trace_hit:
            answer_context, used_tokens, dropped = build_answer_context(
                entities, relationships, chunks, b.max_context_tokens
            )
        else:
            answer_context, used_tokens, dropped = "", 0, 0
            warnings.append("检索没有命中任何实体/关系：answer_context 为空，不会编造内容。")

        if dropped:
            reasons.append("budget_truncated")
            warnings.append(
                f"answer_context 超出 {b.max_context_tokens} token 预算，丢弃 {dropped} 条；"
                "完整内容仍在 hits/trace 里（看得见 ≠ 塞进去）。"
            )

        # evidence_empty：锚点有、证据一条都没有 —— 分层事实上只停在半路。
        # 不作 degraded（上下文本身是可靠的），但必须结构化暴露，不能只缴给 warnings。
        anchors_list = layers.get("anchors") or []
        cited_list = layers.get("cited") or []
        evidence_empty = bool(anchors_list) and not cited_list
        if evidence_empty and result.trace_hit:
            what = "context.task" if used_mode == "agent" else "生成答案"
            warnings.append(
                f"证据层未触发：{what} 里没有字面出现任何图实体名（cited 为空），"
                "当前 answer_context 只有锚点邻域。若这次任务确实涉及具体实体，"
                "在 task / query 里点名，证据层才会亮。"
            )

        reason = next((r for r in REASON_PRIORITY if r in reasons), None)
        if caller:
            logger.info("memory.search caller=%s mode=%s reason=%s", caller, used_mode, reason)

        return {
            "answer_context": answer_context,
            "hits": {
                "entities": entities,
                "relationships": relationships,
                "chunks": chunks,
            },
            "trace": {
                "anchors": layers.get("anchors", []),
                "cited": layers.get("cited", []),
                "paths": layers.get("paths", []),
                "disconnected": layers.get("disconnected", []),
                "recall_only": layers.get("recall_only", []),
                "unmatched_keywords": layers.get("unmatched_keywords", []),
                "anchor_mode": anchor_mode,
                "evidence_empty": evidence_empty,
                "budget_used": {
                    **b.as_dict(),
                    "context_used": used_tokens,
                    "context_dropped": dropped,
                },
                "retrieved": trace.get("retrieved"),
            },
            "degraded": bool(reasons),
            "reason": reason,
            "version": API_VERSION,
            "mode": used_mode,
            "warnings": warnings,
        }

    # ---- memory.ingest ----

    async def ingest(
        self,
        source: str,
        content: str,
        title: str | None = None,
        stable_id: str | None = None,
        origin: str = "extracted",
        wait: bool = False,
    ) -> dict:
        """写入记忆：默认异步（回 job_id 就走），`wait=True` 等到写完再回。

        设计文档里写的是 `async: true/false`——`async` 是 Python 关键字，当不了参数名，
        所以这里叫 `wait`，语义等价（`async: false` == `wait: true`）。
        实测一次抽取约 28s，异步优先是必须的。
        """
        if source not in INGEST_SOURCES:
            raise ValueError(f"source 只能是 {sorted(INGEST_SOURCES)}，收到 {source!r}")
        if not str(content or "").strip():
            raise ValueError("content 不能为空（空文档会白跑一次 LLM 抽取）")

        raw_title = (title or stable_id or "").strip()
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        doc_title = raw_title or f"{source}-{job_id[-8:]}"
        job = Job(job_id=job_id, doc_id=slugify(doc_title), origin=str(origin or "extracted"))
        if job.origin != "extracted":
            job.warnings.append(
                f"origin={job.origin} 目前只记录不落库：溯源标签（M4 / backlog#9）还没做"
            )
        self._register(job)

        if wait:
            await self._run(job, doc_title, content)
            return job.as_dict()

        task = asyncio.create_task(self._run(job, doc_title, content))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.as_dict()

    def ingest_status(self, job_id: str) -> dict:
        job = self._jobs.get(str(job_id))
        if job is None:
            # 不报错：agent 拿到一个结构化答复比吃异常好；但要把「为什么会没有」说清楚
            return {
                "job_id": job_id,
                "status": "unknown",
                "progress": "",
                "error": "未知 job_id：任务表在 MCP 进程内存里，server 重启即清空",
                "result": None,
            }
        return job.as_dict()

    # ---- 内部 ----

    def _register(self, job: Job) -> None:
        self._jobs[job.job_id] = job
        if len(self._jobs) > JOB_RETENTION:
            for old in list(self._jobs.values()):
                if old.status in ("done", "error"):
                    self._jobs.pop(old.job_id, None)
                    break

    async def _run(self, job: Job, title: str, content: str) -> None:
        job.status = "running"
        job.progress = "抽取实体/关系并写图（LightRAG ainsert）"
        try:
            result = await upsert_document(self.rag, title, content)
            job.result = {
                "doc_id": result.doc_id,
                "created": result.created,
                "entity_count": result.entity_count,
                "relation_count": result.relation_count,
            }
            job.status = "done"
            job.progress = "完成"
        except Exception as exc:  # noqa: BLE001 — 任务失败要如实回给调用方，不回滚也不假装成功
            job.status = "error"
            job.progress = "失败"
            job.error = f"{type(exc).__name__}: {exc}"
            logger.exception("memory.ingest 失败 job=%s", job.job_id)
