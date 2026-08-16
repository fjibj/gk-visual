"""HTTP 服务：FastAPI 图 CRUD + 静态托管前端。

落库完全复用 LightRAG 编辑 API（acreate_*/aedit_*/adelete_by_*/amerge_entities）。
编辑操作即时落盘（LightRAG 图存储 upsert 即时写盘，已 spike 验证），
故每个写操作后无需 finalize；仅进程关闭时 finalize 释放资源。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config
from .ingest import _entity_name
from .merge import merge_entities
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    rag = await init_rag(load_config())
    app.state.rag = rag
    yield
    await rag.finalize_storages()


def create_app() -> FastAPI:
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
        if req.description is not None:
            data["description"] = req.description
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

    # ---- 静态前端托管 ----

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
