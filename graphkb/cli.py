"""CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from .config import load_config
from .ingest import ingest_document
from .merge import merge_entities
from .providers import build_embedding, build_llm
from .query import query
from .rag import init_rag


async def _doctor() -> int:
    cfg = load_config()
    print(f"LLM       provider={cfg.llm.provider} model={cfg.llm.model} base={cfg.llm.base_url}")
    print(f"Embedding provider={cfg.embedding.provider} model={cfg.embedding.model} dim={cfg.embedding.dim}")

    llm = build_llm(cfg)
    emb = build_embedding(cfg)

    print("testing LLM ...")
    out = await llm("只回复两个字：收到", system_prompt="你是测试助手")
    print(f"  LLM -> {out!r}")

    print("testing embedding ...")
    vecs = await emb(["你好", "世界"])
    print(f"  embedding shape={vecs.shape} dtype={vecs.dtype}")

    print("initializing LightRAG ...")
    rag = await init_rag(cfg)
    print("  LightRAG initialized OK")
    await rag.finalize_storages()
    print("doctor OK")
    return 0


async def _ingest(path: str) -> int:
    cfg = load_config()
    rag = await init_rag(cfg)
    text = Path(path).read_text(encoding="utf-8")
    result = await ingest_document(rag, text)
    await rag.finalize_storages()

    print(f"doc_id: {result.doc_id}")
    print(f"entity_count: {result.entity_count}")
    print(f"relation_count: {result.relation_count}")
    if result.new_entities:
        print(f"new_entities ({len(result.new_entities)}):")
        for e in result.new_entities:
            print(f"  + {e}")
    else:
        print("new_entities: 无（本次无新增，实体均与已有同名对齐）")
    if result.lost_entities:
        print(f"⚠ 增量丢失 {len(result.lost_entities)} 个实体（图可能被重建）: {result.lost_entities}")
    if result.entity_count == 0:
        print("⚠ 未抽取到实体（文档可能无可抽取内容）")
    print("entities:")
    for e in result.entities:
        print(f"  - {e}")
    print("relations:")
    for s, t in result.relations:
        print(f"  - {s} -> {t}")
    return 0


async def _query(question: str) -> int:
    cfg = load_config()
    rag = await init_rag(cfg)
    result = await query(rag, question)
    await rag.finalize_storages()

    print(f"question: {result.question}")
    print(f"answer: {result.answer}")
    print(f"trace_hit: {result.trace_hit}")
    print("trace:")
    print(json.dumps(result.trace, ensure_ascii=False, indent=2))
    return 0


async def _merge(sources: list[str], target: str) -> int:
    cfg = load_config()
    rag = await init_rag(cfg)
    result = await merge_entities(rag, sources, target)
    await rag.finalize_storages()

    print(f"merged into: {result.target_entity}")
    print(f"deleted_entities: {result.deleted_entities}")
    print(f"relationships_transferred: {result.relationships_transferred}")
    if result.sources_remaining:
        print(f"⚠ 合并后源实体仍残留（半合并）: {result.sources_remaining}")
    print("target_final:")
    print(json.dumps(result.target_final, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="graphkb")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="自检：验证 LLM/embedding/LightRAG 初始化")

    p_ingest = sub.add_parser("ingest", help="摄入单个文档（UTF-8 文本）")
    p_ingest.add_argument("path", help="文档路径")

    p_query = sub.add_parser("query", help="检索问答（返回答案 + 结构化 trace）")
    p_query.add_argument("question", help="问题")

    p_merge = sub.add_parser("merge", help="显式合并实体（源并入目标，复用 LightRAG 对齐）")
    p_merge.add_argument("sources", nargs="+", help="要合并并删除的源实体名（一个或多个）")
    p_merge.add_argument("--into", required=True, dest="target", help="合并后的目标实体名")

    args = parser.parse_args()
    load_dotenv()

    if args.cmd == "doctor":
        raise SystemExit(asyncio.run(_doctor()))
    if args.cmd == "ingest":
        raise SystemExit(asyncio.run(_ingest(args.path)))
    if args.cmd == "query":
        raise SystemExit(asyncio.run(_query(args.question)))
    if args.cmd == "merge":
        raise SystemExit(asyncio.run(_merge(args.sources, args.target)))
    parser.print_help()


if __name__ == "__main__":
    main()
