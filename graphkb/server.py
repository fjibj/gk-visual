"""HTTP 服务：FastAPI 图 CRUD + 文档上传/解析 + 静态托管前端。

落库完全复用 LightRAG 编辑 API（acreate_*/aedit_*/adelete_by_*/amerge_entities）。
编辑操作即时落盘（LightRAG 图存储 upsert 即时写盘，已 spike 验证），
故每个写操作后无需 finalize；仅进程关闭时 finalize 释放资源。

文档上传（/api/documents/upload）：格式解析复用 LightRAG 自带 legacy 解析层
（lightrag.parser.legacy.extract_text，内部按需 import pypdf/python-docx/
python-pptx/openpyxl），本项目不写任何格式解析器；解析出纯文本后走 S6 的
upsert_document 管线（标题 slug = doc_id，同标题重传即覆盖更新）。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from lightrag.parser.legacy import LegacyExtractionError, extract_text
from pydantic import BaseModel

from .config import load_config
from .documents import list_documents, upsert_document
from .ingest import _entity_name
from .merge import merge_entities
from .query import query as run_query
from .rag import init_rag


# ---- 请求/响应模型 ----

class EntityCreate(BaseModel):
    name: str
    type: Optional[str] = None
    description: Optional[str] = None


class EntityUpdate(BaseModel):
    type: Optional[str] = None
    description: Optional[str] = None


class RelationBody(BaseModel):
    source: str
    target: str
    description: Optional[str] = None
    keywords: Optional[str] = None


class MergeBody(BaseModel):
    sources: list[str]
    target: str


class DocumentBody(BaseModel):
    title: str
    content: str


# 上传允许的格式（白名单）。txt/md 走解码，其余交给 LightRAG legacy 解析器。
SUPPORTED_UPLOAD_SUFFIXES = frozenset({"txt", "md", "docx", "xlsx", "pptx", "pdf"})


# ---- 读图 ----

async def _read_graph(rag) -> dict:
    nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
    edges = await rag.chunk_entity_relation_graph.get_all_edges()
    return {
        "nodes": [
            {
                "id": _entity_name(n),
                "type": n.get("entity_type") or "",
                "description": n.get("description") or "",
            }
            for n in nodes
        ],
        "edges": [
            {
                "source": str(e.get("source", "")),
                "target": str(e.get("target", "")),
                "description": e.get("description") or "",
                "keywords": e.get("keywords") or "",
                "weight": e.get("weight"),
            }
            for e in edges
        ],
    }


# ---- app 生命周期 ----

def create_app(config=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()
        cfg = config if config is not None else load_config()
        rag = await init_rag(cfg)
        app.state.rag = rag
        app.state.cfg = cfg
        yield
        await rag.finalize_storages()

    app = FastAPI(title="graphkb", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/graph")
    async def get_graph(request: Request):
        return await _read_graph(request.app.state.rag)

    # ---- 实体 ----

    @app.post("/api/entities", status_code=201)
    async def create_entity(req: EntityCreate, request: Request):
        data: dict = {}
        # LightRAG 要求 description 非空；用户不填时用实体名兑底
        data["description"] = (req.description or "").strip() or req.name
        if req.type is not None:
            data["entity_type"] = req.type
        try:
            result = await request.app.state.rag.acreate_entity(req.name, data)
        except Exception as exc:  # 重名/空名等
            raise HTTPException(status_code=400, detail=f"创建实体失败: {exc}") from exc
        return {"name": result.get("entity_name") or req.name}

    @app.patch("/api/entities/{name}")
    async def edit_entity(name: str, req: EntityUpdate, request: Request):
        data: dict = {}
        if req.description is not None:
            data["description"] = req.description
        if req.type is not None:
            data["entity_type"] = req.type
        if not data:
            raise HTTPException(status_code=400, detail="没有可更新的字段")
        try:
            result = await request.app.state.rag.aedit_entity(name, data)
        except Exception as exc:  # 实体不存在/空描述等
            raise HTTPException(status_code=404, detail=f"实体不存在或不可编辑: {exc}") from exc
        return {"name": result.get("entity_name") or name}

    @app.delete("/api/entities/{name}")
    async def delete_entity(name: str, request: Request):
        result = await request.app.state.rag.adelete_by_entity(name)
        if result.status != "success":
            raise HTTPException(status_code=404, detail=result.message or f"实体不存在: {name}")
        return {"name": name, "status": result.status}

    # ---- 关系 ----

    @app.post("/api/relations", status_code=201)
    async def create_relation(req: RelationBody, request: Request):
        data: dict = {}
        if req.description is not None:
            data["description"] = req.description
        if req.keywords is not None:
            data["keywords"] = req.keywords
        try:
            result = await request.app.state.rag.acreate_relation(req.source, req.target, data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"创建关系失败: {exc}") from exc
        return {"source": req.source, "target": req.target}

    @app.patch("/api/relations")
    async def edit_relation(req: RelationBody, request: Request):
        data: dict = {}
        if req.description is not None:
            data["description"] = req.description
        if req.keywords is not None:
            data["keywords"] = req.keywords
        if not data:
            raise HTTPException(status_code=400, detail="没有可更新的字段")
        try:
            await request.app.state.rag.aedit_relation(req.source, req.target, data)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"关系不存在或不可编辑: {exc}") from exc
        return {"source": req.source, "target": req.target}

    @app.delete("/api/relations")
    async def delete_relation(source: str, target: str, request: Request):
        result = await request.app.state.rag.adelete_by_relation(source, target)
        if result.status != "success":
            raise HTTPException(status_code=404, detail=result.message or "关系不存在")
        return {"source": source, "target": target, "status": result.status}

    # ---- 合并 ----

    @app.post("/api/merge")
    async def merge(req: MergeBody, request: Request):
        try:
            result = await merge_entities(request.app.state.rag, req.sources, req.target)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"合并失败: {exc}") from exc
        return {
            "target": result.target_entity,
            "deleted": result.deleted_entities,
            "relationships_transferred": result.relationships_transferred,
            "sources_remaining": result.sources_remaining,
        }

    # ---- 文档 -------

    @app.post("/api/documents", status_code=201)
    async def create_document(req: DocumentBody, request: Request):
        if not req.content.strip():
            raise HTTPException(status_code=400, detail="文档内容不能为空")
        try:
            result = await upsert_document(request.app.state.rag, req.title, req.content)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"上传文档失败: {exc}") from exc
        return {
            "doc_id": result.doc_id,
            "created": result.created,
            "entity_count": result.entity_count,
            "relation_count": result.relation_count,
        }

    @app.post("/api/documents/upload", status_code=201)
    async def upload_document_file(
        request: Request,
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
    ):
        """上传真实文件 → 解析成纯文本 → 走 S6 upsert_document（同标题 = 覆盖更新）。

        解析失败/不支持格式/抽不出文本一律 4xx 明说，绝不静默入库（Failure 2/3/5）。
        大小上限读配置（GKB_MAX_UPLOAD_MB，默认 50MB），超限直接 413。
        """
        filename = (file.filename or "").strip()
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式「{suffix or '(无扩展名)'}」。支持: "
                f"{', '.join(sorted(SUPPORTED_UPLOAD_SUFFIXES))}",
            )

        max_mb = request.app.state.cfg.max_upload_mb
        max_bytes = max_mb * 1024 * 1024
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"文件超过大小上限 {max_mb}MB，已拒绝"
            )
        if not data:
            raise HTTPException(status_code=400, detail="空文件")

        try:
            # 解析是同步 CPU 活，丢线程避免卡事件循环
            text = await asyncio.to_thread(extract_text, data, suffix)
        except LegacyExtractionError as exc:
            raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"文件解析失败（文件可能已损坏或格式不符）: {type(exc).__name__}: {exc}",
            ) from exc
        text = text.strip()
        if not text:
            raise HTTPException(
                status_code=400,
                detail="该文件抽不出文本（若是 PDF，可能是扫描版无文本层，需 OCR）",
            )

        stem = filename.rsplit(".", 1)[0].strip() or "untitled"
        doc_title = (title or "").strip() or stem
        try:
            result = await upsert_document(request.app.state.rag, doc_title, text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"入库失败: {exc}") from exc
        return {
            "doc_id": result.doc_id,
            "title": doc_title,
            "chars": len(text),
            "created": result.created,
            "entity_count": result.entity_count,
            "relation_count": result.relation_count,
        }

    @app.get("/api/documents")
    async def get_documents(request: Request):
        docs = await list_documents(request.app.state.rag)
        return {"documents": [d.__dict__ for d in docs]}

    @app.delete("/api/documents/{doc_id}")
    async def delete_doc(doc_id: str, request: Request):
        result = await request.app.state.rag.adelete_by_doc_id(doc_id)
        if result.status != "success":
            raise HTTPException(status_code=404, detail=result.message or f"文档不存在: {doc_id}")
        return {"doc_id": doc_id, "status": result.status}

    # ---- 检索 -------

    @app.get("/api/query")
    async def query_endpoint(question: str, request: Request):
        result = await run_query(
            request.app.state.rag, question, budget=request.app.state.cfg.retrieval
        )
        return {"answer": result.answer, "trace": result.trace, "trace_hit": result.trace_hit}

    # ---- 静态前端托管 ----

    @app.middleware("http")
    async def _no_cache_frontend(request: Request, call_next):
        """防陈旧前端：index.html 与 /api/* 不被浏览器强缓存（否则改完前端刷新看不到新构建）。

        带 hash 的 assets 不改——它们文件名变了就自然失效。
        """
        response = await call_next(request)
        path = request.url.path
        if path.endswith(".html") or path == "/" or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("graphkb.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
