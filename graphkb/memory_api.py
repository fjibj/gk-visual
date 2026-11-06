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

try:  # 只是为把 LightRAG 的多段描述拆开显示；拿不到就按约定值兜底
    from lightrag.utils import GRAPH_FIELD_SEP
except Exception:  # noqa: BLE001
    GRAPH_FIELD_SEP = "<SEP>"

logger = logging.getLogger(__name__)

API_VERSION = "1"

DEFAULT_MAX_CONTEXT_TOKENS = 800
"""answer_context 的默认预算（token）。断崖式调大之前先看 Inline&Spill 的溢出清单。"""

DESC_CLIP = 240  # 实体/关系描述进上下文时最多保留多少字（全文靠 spill_ref 取回）
CHUNK_CLIP = 400  # 块内容进上下文时最多保留多少字
SPILL_SUMMARY_CHARS = 60  # spill_ref 的一行摘要多少字

MAX_EXPAND_ITEMS = 20  # memory.expand 一次最多取回几条，防止被当批量导出器用
DEFAULT_EXPAND_MAX_TOKENS = 2000  # 单条取回内容的默认预算

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


def _plain(text: str) -> str:
    """把 LightRAG 用 <SEP> 拼起来的多段描述抖开成可读文本（去空、去重、保序）。"""
    parts: list[str] = []
    for p in str(text or "").split(GRAPH_FIELD_SEP):
        p = " ".join(p.split())
        if p and p not in parts:
            parts.append(p)
    return "；".join(parts)


def _layer_rank(layer: str | None) -> int:
    return {"anchor": 0, "cited": 1, "path": 2, "direct": 0}.get(layer or "", 9)


# ---------------------------------------------------------------- Inline & Spill


def entity_ref(name: str) -> str:
    return f"entity:{name}"


def relation_ref(src: str, tgt: str) -> str:
    return f"relation:{src}->{tgt}"


def chunk_ref(chunk_id: str) -> str:
    return f"chunk:{chunk_id}"


@dataclass
class Candidate:
    """一条可注入的内容。装得下就 Inline，装不下就变成 spill_ref 等着被取。"""

    kind: str  # entity | relation | chunk
    ref: str
    line: str  # 进 answer_context 的那一行
    summary: str  # 进 spill_refs 的一行摘要（不占注入预算）
    tokens: int  # 取回它要花的预算，让调用方自己决定值不值


@dataclass
class ContextBundle:
    text: str = ""
    used_tokens: int = 0
    inline_count: int = 0
    spill_refs: list[dict] = field(default_factory=list)
    spilled_tokens: int = 0

    def budget_trace(self) -> dict:
        return {
            "context_used": self.used_tokens,
            "context_inline": self.inline_count,
            "context_spilled": len(self.spill_refs),
            "spilled_tokens": self.spilled_tokens,
        }


def _entity_candidate(e: dict) -> Candidate | None:
    name = str(e.get("name") or "")
    if not name:
        return None
    layer = e.get("layer") or "entity"
    line = f"[{layer}] {name}"
    if e.get("type"):
        line += f"（{e['type']}）"
    desc = _plain(e.get("description"))
    if desc:
        line += f"：{_clip(desc, DESC_CLIP)}"
    summary = name + (f"（{e['type']}）" if e.get("type") else "")
    if desc:
        summary += f"：{_clip(desc, SPILL_SUMMARY_CHARS)}"
    return Candidate("entity", entity_ref(name), line, summary, estimate_tokens(line) + 1)


def _relation_candidate(r: dict) -> Candidate | None:
    src, tgt = str(r.get("src") or ""), str(r.get("tgt") or "")
    if not src or not tgt:
        return None
    layer = r.get("layer") or "edge"
    desc = _plain(r.get("description"))
    line = f"[{layer}] {src} -> {tgt}"
    if r.get("keywords"):
        line += f"［{_plain(r.get('keywords'))}］"
    if desc:
        line += f"：{_clip(desc, DESC_CLIP)}"
    summary = f"{src} -> {tgt}" + (f"：{_clip(desc, SPILL_SUMMARY_CHARS)}" if desc else "")
    return Candidate("relation", relation_ref(src, tgt), line, summary, estimate_tokens(line) + 1)


def _chunk_candidate(c: dict) -> Candidate | None:
    cid = str(c.get("chunk_id") or "")
    content = _clip(c.get("content") or "", CHUNK_CLIP)
    if not cid or not content:
        return None
    line = f"[chunk] {content}"
    return Candidate("chunk", chunk_ref(cid), line, _clip(content, SPILL_SUMMARY_CHARS), estimate_tokens(line) + 1)


def build_answer_context(
    entities: list[dict],
    relationships: list[dict],
    chunks: list[dict],
    max_tokens: int,
) -> ContextBundle:
    """Inline & Spill：预算内的进 `answer_context`，超出的变成 `spill_refs`。

    两条规矩：
    · 注入内容只从这里出（零 LLM、可复算、确定性顺序：anchor → cited → path → 关系 → 块）；
    · **溢出不是丢弃**——预算是「展示预算」，不是「语义筛」。装不下的保留引用 + 一行摘要，
      调用方需要时再取（这是 claude-mem 那种「全塞进 prompt」与「默默丢掉」之外的第三条路）。
    """
    cands: list[Candidate] = []
    for e in sorted(entities, key=lambda x: (_layer_rank(x.get("layer")), str(x.get("name") or ""))):
        c = _entity_candidate(e)
        if c:
            cands.append(c)
    for r in sorted(relationships, key=lambda x: _layer_rank(x.get("layer"))):
        c = _relation_candidate(r)
        if c:
            cands.append(c)
    for raw in chunks:
        c = _chunk_candidate(raw)
        if c:
            cands.append(c)

    bundle = ContextBundle()
    seen: set[str] = set()
    lines: list[str] = []
    for c in cands:
        if c.ref in seen:  # 同一引用只留一条（路径实体常同时出现在实体表与关系表里）
            continue
        seen.add(c.ref)
        if bundle.used_tokens + c.tokens <= max_tokens:
            lines.append(c.line)
            bundle.used_tokens += c.tokens
            bundle.inline_count += 1
        else:
            bundle.spill_refs.append(
                {"ref": c.ref, "kind": c.kind, "summary": c.summary, "tokens": c.tokens}
            )
            bundle.spilled_tokens += c.tokens
    bundle.text = "\n".join(lines)
    return bundle


# ---------------------------------------------------------------- 写入任务


def _entity_text(name: str, node: dict) -> str:
    etype = node.get("entity_type") or node.get("type") or ""
    head = name + (f"（{etype}）" if etype else "")
    desc = _plain(node.get("description"))
    return head + (f"：{desc}" if desc else "")


def _relation_text(src: str, tgt: str, edge: dict) -> str:
    head = f"{src} -> {tgt}"
    keywords = _plain(edge.get("keywords"))
    if keywords:
        head += f"［{keywords}］"
    desc = _plain(edge.get("description"))
    return head + (f"：{desc}" if desc else "")


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
    """`memory.*` 四个工具的落点（search / expand / ingest / ingest_status）。

    构造即绑定 workspace（由 MCP server 启动时决定）。
    """

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
            bundle = build_answer_context(entities, relationships, chunks, b.max_context_tokens)
        else:
            bundle = ContextBundle()
            warnings.append("检索没有命中任何实体/关系：answer_context 为空，不会编造内容。")

        if bundle.spill_refs:
            reasons.append("budget_truncated")
            warnings.append(
                f"answer_context 只装下 {bundle.inline_count} 条 / {bundle.used_tokens} token"
                f"（预算 {b.max_context_tokens}）；另有 {len(bundle.spill_refs)} 条"
                f"（≈{bundle.spilled_tokens} token）没进注入，已放进 spill_refs，"
                "需要时用 memory.expand 取回——是溢出，不是丢弃。"
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
            "answer_context": bundle.text,
            "spill_refs": bundle.spill_refs,
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
                    **bundle.budget_trace(),
                },
                "retrieved": trace.get("retrieved"),
            },
            "degraded": bool(reasons),
            "reason": reason,
            "version": API_VERSION,
            "mode": used_mode,
            "warnings": warnings,
        }

    # ---- memory.expand ----

    async def expand(self, refs, max_tokens: int = DEFAULT_EXPAND_MAX_TOKENS) -> dict:
        """把 `spill_refs` 里的引用取回原文。

        引用是**无状态的**：`entity:张三` / `relation:张三->字节跳动` / `chunk:c123`
        直接指向图与块存储，不靠进程内缓存。所以 server 重启、换一次会话，引用照样能取——
        这比在内存里存一份 spill 内容实在（代价是只适用于“还在库里”的东西，被删就取不到，
        此时如实报 missing 而不是编）。
        """
        if isinstance(refs, str):
            refs = [refs]
        if not refs:
            raise ValueError("refs 不能为空")
        if len(refs) > MAX_EXPAND_ITEMS:
            raise ValueError(f"一次最多取 {MAX_EXPAND_ITEMS} 条，收到 {len(refs)}")
        cap = _int(max_tokens, DEFAULT_EXPAND_MAX_TOKENS)
        if cap < 1:
            raise ValueError(f"max_tokens 必须 ≥1，收到 {cap}")

        items: list[dict] = []
        missing: list[dict] = []
        for raw in refs:
            ref = str(raw).strip()
            kind, _, key = ref.partition(":")
            text: str | None = None
            reason: str | None = None
            try:
                if kind == "entity":
                    node = await self.rag.chunk_entity_relation_graph.get_node(key)
                    if node:
                        text = _entity_text(key, node)
                    else:
                        reason = "图里没有这个实体（可能已删除或改名）"
                elif kind == "relation":
                    src, sep, tgt = key.partition("->")
                    if not sep:
                        reason = "关系引用应形如 relation:A->B"
                    else:
                        edge = await self.rag.chunk_entity_relation_graph.get_edge(src, tgt)
                        if edge:
                            text = _relation_text(src, tgt, edge)
                        else:
                            reason = "图里没有这条关系（可能两端改名或边已删）"
                elif kind == "chunk":
                    row = await self.rag.text_chunks.get_by_id(key)
                    if row:
                        text = str(row.get("content") or "")
                    else:
                        reason = "块存储里没有这个 chunk（所属文档可能被覆盖或删除）"
                else:
                    reason = "未知引用类型（只认 entity: / relation: / chunk:）"
            except Exception as exc:  # noqa: BLE001 — 取不到就说取不到，不矞着调用方
                reason = f"取回失败：{type(exc).__name__}: {exc}"

            if text is None:
                missing.append({"ref": ref, "reason": reason or "取不到"})
                continue
            tokens = estimate_tokens(text)
            truncated = tokens > cap
            if truncated:
                keep = max(1, int(len(text) * cap / max(tokens, 1)))
                text = text[:keep] + "…"
            items.append(
                {"ref": ref, "kind": kind, "text": text, "tokens": tokens, "truncated": truncated}
            )
        return {"items": items, "missing": missing, "version": API_VERSION}

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
