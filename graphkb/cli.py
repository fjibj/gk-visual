"""CLI 入口。当前（S1 子切片①）只实现 doctor 自检；ingest/query 后续子切片接入。"""

from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from .config import load_config
from .providers import build_embedding, build_llm


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
    from .rag import init_rag

    rag = await init_rag(cfg)
    print("  LightRAG initialized OK")
    await rag.finalize_storages()
    print("doctor OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="graphkb")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="自检：验证 LLM/embedding/LightRAG 初始化")

    # 占位（子切片②③④ 实现）
    sub.add_parser("ingest", help="摄入文档（待实现）")
    sub.add_parser("query", help="检索问答（待实现）")

    args = parser.parse_args()
    load_dotenv()

    if args.cmd == "doctor":
        raise SystemExit(asyncio.run(_doctor()))
    if args.cmd in ("ingest", "query"):
        print(f"'{args.cmd}' 尚未实现（后续子切片接入）")
        raise SystemExit(1)
    parser.print_help()


if __name__ == "__main__":
    main()
