"""判卷机专用端点（`GKB_TEST_MODE=1` 才挂载；生产环境不存在）。

为什么要有这一层：idsd-harness v3 的判卷机是 Node + HTTP，而 gk-visual 的检索
真身在 `graphkb.memory_api.MemoryTools.search`（MCP 走 stdio，判卷机够不着）。
这些端点只是**给同一个函数换了个入口**——测的仍是真实现，不是替身。

三条硬规矩（手册 §3.3 / §6.1）：
  · 只在 `GKB_TEST_MODE` 打开时注册，生产跑不起来（`create_app()` 里判断）；
  · reset 必须把 KV / 向量 / 图三部分一起清干净，否则上个场景的实体会被下个场景召回到；
  · 端点不实现任何判据逻辑：trace_hash 只是把 trace 排序后求 sha256，不参与判定。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .config import REPO_ROOT
from .memory_api import MemoryTools
from .rag import reset_rag

logger = logging.getLogger(__name__)

FIXTURE_ROOT = REPO_ROOT / "holdout" / "fixtures"
"""预置夹具目录：一个子目录 = 一份可以直接铺进 working_dir 的库。"""

TRUTHY = frozenset({"1", "true", "yes", "on"})


def test_mode_enabled() -> bool:
    return str(os.environ.get("GKB_TEST_MODE", "")).strip().lower() in TRUTHY


# ---- 从 trace 里抽出可以比较的东西 ----


def _node_names(trace: dict) -> set[str]:
    """trace 里被引用到的全部实体名（锚点 / 引用点 / 路径中间节点）。"""
    layers = trace.get("hit_layers") or {}
    names = {str(x) for x in (layers.get("anchors") or [])}
    names |= {str(x) for x in (layers.get("cited") or [])}
    for record in layers.get("paths") or []:
        for one_path in record.get("paths") or []:
            names |= {str(x) for x in one_path}
    return names


def trace_hash(trace: dict) -> str:
    """把「锚点 / 引用点 / 路径」规范化后求 sha256。

    刻意**不含** `retrieved` 与 `recall_only`：那两处是向量召回的产物，受 top_k 与
    embedding 浮点抖动影响，属于「召回噪声」而不是判据。PROP-01 要守的是判据的
    确定性，拿噪声去哈希只会得到一个永远红的属性。
    也刻意不用内置 `hash()`：跨进程随机化，同一份数据两次跑都对不上。
    """
    layers = trace.get("hit_layers") or {}
    canonical = {
        "anchors": sorted(str(x) for x in (layers.get("anchors") or [])),
        "cited": sorted(str(x) for x in (layers.get("cited") or [])),
        "paths": sorted(
            json.dumps(
                {
                    "from": str(record.get("from")),
                    "to": str(record.get("to")),
                    "kind": str(record.get("kind")),
                    "paths": sorted(
                        [str(x) for x in one_path] for one_path in record.get("paths") or []
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for record in layers.get("paths") or []
        ),
        "disconnected": sorted(
            json.dumps(
                {"a": str(d.get("a")), "b": str(d.get("b")), "kind": str(d.get("kind"))},
                ensure_ascii=False,
                sort_keys=True,
            )
            for d in layers.get("disconnected") or []
        ),
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


async def graph_node_names(rag) -> set[str]:
    return {str(node.get("id")) for node in await rag.chunk_entity_relation_graph.get_all_nodes()}


# ---- 请求体 ----


class ResetBody(BaseModel):
    fixture: str | None = None


class SearchBody(BaseModel):
    question: str
    evidence_text: str | None = None
    budget: int | None = None
    mode: str = "agent"


# ---- 路由 ----


def build_test_router() -> APIRouter:
    router = APIRouter(prefix="/api/_test", tags=["test-only"])

    @router.post("/reset")
    async def reset(request: Request, body: ResetBody | None = None):
        """清库（可选铺夹具）并重建实例。判卷机在每个场景 / 每次 property 迭代前调用。"""
        app = request.app
        cfg = app.state.cfg
        name = (body.fixture if body else None) or None
        fixture_dir: Path | None = None
        if name:
            if "/" in name or "\\" in name or name in (".", ".."):
                raise HTTPException(status_code=400, detail=f"夹具名不合法: {name!r}")
            fixture_dir = FIXTURE_ROOT / name
            if not fixture_dir.is_dir():
                raise HTTPException(status_code=404, detail=f"没有这个夹具: {name}")

        app.state.rag = await reset_rag(app.state.rag, cfg, fixture_dir=fixture_dir)
        nodes = await app.state.rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await app.state.rag.chunk_entity_relation_graph.get_all_edges()
        return {
            "reset": True,
            "fixture": name,
            "working_dir": str(cfg.working_dir),
            "nodes": len(nodes),
            "edges": len(edges),
        }

    @router.post("/memory_search")
    async def memory_search(request: Request, body: SearchBody):
        """直接调 `MemoryTools.search`（MCP 的同一函数），并附上判卷机要的几个派生字段。"""
        question = (body.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question 不能为空")
        evidence = (body.evidence_text or "").strip()
        budget = {"max_context_tokens": body.budget} if body.budget else None
        tools = MemoryTools(request.app.state.cfg, request.app.state.rag)
        try:
            out = await tools.search(
                context={"query": question, "task": evidence or question},
                budget=budget,
                mode="agent" if evidence else "auto",
            )
        except ValueError as exc:  # 参数问题：400 而不 500，判卷机才看得出是考题错
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            # 上游（LLM / embedding）挂了时把原因原样带出去：500 只有一个空 body，
            # 判卷机只能看到「got 500」，分诊时分不清是出题错、实现错还是模型不可用。
            logger.warning("测试端点 memory_search 上游失败：%s: %s", type(exc).__name__, exc)
            raise HTTPException(
                status_code=502,
                detail=f"上游不可用（{type(exc).__name__}）: {str(exc)[:300]}",
            ) from exc

        trace = out.get("trace") or {}
        names = _node_names(trace)
        known = await graph_node_names(request.app.state.rag)
        dangling = sorted(names - known)
        budget_used = trace.get("budget_used") or {}
        return {
            "trace_hash": trace_hash(trace),
            "trace_dangling_count": len(dangling),
            "dangling": dangling,
            "context_tokens": budget_used.get("context_used"),
            "context_chars": len(out.get("answer_context") or ""),
            "anchors": trace.get("anchors") or [],
            "cited": trace.get("cited") or [],
            "path_count": len(trace.get("paths") or []),
            "spill_count": len(out.get("spill_refs") or []),
            "degraded": out.get("degraded"),
            "reason": out.get("reason"),
            "mode": out.get("mode"),
            "answer_context": out.get("answer_context"),
        }

    @router.get("/state")
    async def state(request: Request):
        """当前库规模（场景里用来断言「重置真的清空了」）。"""
        rag = request.app.state.rag
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        docs = []
        try:
            from .documents import list_documents

            docs = [d.doc_id for d in await list_documents(rag)]
        except Exception:  # noqa: BLE001 — 文档层挂了不该让探针也挂
            docs = []
        return {"nodes": len(nodes), "edges": len(edges), "documents": docs}

    return router
