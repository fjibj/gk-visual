"""生成判卷机用的预置夹具（`holdout/fixtures/<name>/`）——**不需要 LLM**。

为什么要预置：gk-visual 的 ingest 是 30 秒级的 LLM 操作。十几个场景每个都从零灌文档，
一套跑十分钟，而场景要验的是检索/编辑语义，不是「能不能灌进去」。所以只有测 ingest
的场景走真实上传，其余场景铺一份已经建好的库。

为什么手搓而不是 `upsert_document`：手搓只用**图 + 分块 + embedding**（bge-m3 本地跑），
不需要 chat 模型，所以预置数据可以在没有 LLM 订阅的情况下重建、可复现、零成本。
库的形状与 `upsert_document` 灌出来的保持一致（图节点的 `source_id` 指向真实 chunk id，
`memory.expand` / 溯源 / 块关联都按真链路走）。

用法：

    python scripts/make_holdout_fixtures.py [--name kb-small]

产物默认**不含** `llm_response_cache`：留着它，检索时的关键词抽取会直接命中缓存，
PROP-01 的确定性就变成「缓存命中」而不是「判据确定」，等于没测。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from graphkb.config import load_config, load_repo_dotenv  # noqa: E402
from graphkb.rag import init_rag  # noqa: E402

# ---- 夹具语料：合成内容，无真实人物/公司 ----
# 结构是刻意的：一条主干（张三 —云栈科技— 成都分部）、一条旁支（李雷 —南京大学—），
# 这样「两跳」和「不连通」两种情形在同一张图里都能出题。

DOCS: list[dict] = [
    {
        "doc_id": "doc-yunzhan",
        "title": "云栈科技概况",
        "chunks": [
            "云栈科技是一家电商基础设施公司，总部设在北京中关村。"
            "公司创始人叫李雷，李雷毕业于南京大学。",
            "云栈科技在成都设有研发分部，成都分部负责仓储调度系统，"
            "由王敏担任负责人。",
        ],
    },
    {
        "doc_id": "doc-zhangsan",
        "title": "张三的任职",
        "chunks": [
            "张三是一位后端工程师，2020 年加入云栈科技，负责订单系统。"
            "张三的工作地点在北京中关村。",
            "张三和李雷每周开一次技术评审会，会议记录由王敏整理。",
        ],
    },
]

# (name, entity_type, description, chunk_ids)
ENTITIES: list[tuple[str, str, str, list[str]]] = [
    ("张三", "person", "后端工程师，2020 年加入云栈科技，负责订单系统，工作地点在北京中关村。",
     ["doc-zhangsan-chunk-000"]),
    ("李雷", "person", "云栈科技创始人，毕业于南京大学，每周与张三开技术评审会。",
     ["doc-yunzhan-chunk-000", "doc-zhangsan-chunk-001"]),
    ("王敏", "person", "成都研发分部负责人，负责仓储调度系统，整理技术评审会记录。",
     ["doc-yunzhan-chunk-001", "doc-zhangsan-chunk-001"]),
    ("云栈科技", "organization", "电商基础设施公司，总部在北京中关村，在成都设有研发分部。",
     ["doc-yunzhan-chunk-000", "doc-yunzhan-chunk-001", "doc-zhangsan-chunk-000"]),
    ("北京中关村", "location", "云栈科技总部所在地，也是张三的工作地点。",
     ["doc-yunzhan-chunk-000", "doc-zhangsan-chunk-000"]),
    ("成都", "location", "云栈科技研发分部所在地，负责仓储调度系统。",
     ["doc-yunzhan-chunk-001"]),
    ("南京大学", "organization", "李雷的母校。", ["doc-yunzhan-chunk-000"]),
    ("订单系统", "product", "张三负责的系统。", ["doc-zhangsan-chunk-000"]),
    ("仓储调度系统", "product", "成都分部负责的系统。", ["doc-yunzhan-chunk-001"]),
]

# (src, tgt, description, keywords)
RELATIONS: list[tuple[str, str, str, str]] = [
    ("张三", "云栈科技", "张三于 2020 年加入云栈科技，负责订单系统。", "任职,加入"),
    ("张三", "北京中关村", "张三的工作地点在北京中关村。", "工作地点"),
    ("张三", "订单系统", "张三负责订单系统。", "负责"),
    ("张三", "李雷", "张三与李雷每周开一次技术评审会。", "同事,评审会"),
    ("李雷", "云栈科技", "李雷是云栈科技的创始人。", "创始人"),
    ("李雷", "南京大学", "李雷毕业于南京大学。", "毕业"),
    ("云栈科技", "北京中关村", "云栈科技总部设在北京中关村。", "总部"),
    ("云栈科技", "成都", "云栈科技在成都设有研发分部。", "分部"),
    ("成都", "仓储调度系统", "成都分部负责仓储调度系统。", "负责"),
    ("王敏", "成都", "王敏在成都担任研发分部负责人。", "负责人"),
    ("王敏", "仓储调度系统", "王敏负责仓储调度系统的团队。", "负责"),
    ("王敏", "李雷", "王敏整理技术评审会记录，会议由李雷主持。", "同事,会议"),
]

SKIP_PREFIXES = ("llm_response_cache",)


def _chunk_text(chunk_id: str) -> tuple[str, str]:
    doc_id, _, rest = chunk_id.rpartition("-chunk-")
    for doc in DOCS:
        if doc["doc_id"] != doc_id:
            continue
        idx = int(rest)
        return doc["chunks"][idx], doc["title"]
    raise KeyError(chunk_id)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


STORAGE_ATTRS = (
    "text_chunks",
    "full_docs",
    "full_entities",
    "full_relations",
    "entity_chunks",
    "relation_chunks",
    "doc_status",
    "chunk_entity_relation_graph",
    "entities_vdb",
    "relationships_vdb",
    "chunks_vdb",
)


async def _flush_all(rag) -> None:
    """逐个存储调 `index_done_callback`（把内存里的改动写到磁盘）。"""
    for attr in STORAGE_ATTRS:
        store = getattr(rag, attr, None)
        cb = getattr(store, "index_done_callback", None)
        if cb is None:
            continue
        try:
            await cb()
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {attr}.index_done_callback 失败: {type(exc).__name__}: {exc}")


async def build(dir_path: Path) -> dict:
    load_repo_dotenv()
    cfg = load_config()
    cfg.working_dir = str(dir_path)
    cfg.workspace = ""

    rag = await init_rag(cfg)
    try:
        graph = rag.chunk_entity_relation_graph

        # ---- 块与文档 ----
        chunks: list[dict] = []
        for doc in DOCS:
            rows = {}
            for i, text in enumerate(doc["chunks"]):
                chunk_id = f"{doc['doc_id']}-chunk-{i:03d}"
                rows[chunk_id] = {
                    "tokens": len(text),
                    "content": text,
                    "chunk_order_index": i,
                    "full_doc_id": doc["doc_id"],
                    "file_path": doc["title"],
                }
                chunks.append({"chunk_id": chunk_id, "text": text, "title": doc["title"],
                               "doc_id": doc["doc_id"]})
            await rag.text_chunks.upsert(rows)
            await rag.full_docs.upsert(
                {
                    doc["doc_id"]: {
                        "content": "\n".join(doc["chunks"]),
                        "file_path": doc["title"],
                    }
                }
            )
            await rag.doc_status.upsert(
                {
                    doc["doc_id"]: {
                        "status": "processed",
                        "content_summary": " ".join(doc["chunks"])[:200],
                        "content_length": sum(len(c) for c in doc["chunks"]),
                        "chunks_count": len(doc["chunks"]),
                        # `chunks_list` 是文档→块的反向索引：`list_documents` 靠它算
                        # 「这篇文档贡献了多少实体」，缺了它统计恒为 0。
                        "chunks_list": [
                            f"{doc['doc_id']}-chunk-{i:03d}" for i in range(len(doc["chunks"]))
                        ],
                        "created_at": _now(),
                        "updated_at": _now(),
                        "file_path": doc["title"],
                    }
                }
            )

        # ---- 图 ----
        for name, etype, desc, chunk_ids in ENTITIES:
            await graph.upsert_node(
                name,
                {
                    "entity_id": name,
                    "entity_type": etype,
                    "description": desc,
                    "source_id": "<SEP>".join(chunk_ids),
                    "file_path": _chunk_text(chunk_ids[0])[1],
                },
            )
        for src, tgt, desc, kw in RELATIONS:
            src_chunks = [c for n, _t, _d, cs in ENTITIES if n == src for c in cs]
            await graph.upsert_edge(
                src,
                tgt,
                {
                    "description": desc,
                    "keywords": kw,
                    "source_id": "<SEP>".join(src_chunks[:2]),
                    "file_path": "manual_creation",
                    "weight": 1.0,
                },
            )

        # ---- 贡献锚点（full_entities / full_relations / *_chunks）----
        # 这四张表是偏本账：**删文档时 LightRAG 靠它们找到该删哪些实体**，
        # 缺了它们 `adelete_by_doc_id` 会「成功」但图上什么也不动
        # （2026-11-21 的 observe 首轮就是这么红的：张三 该没消失）。
        # 它们不是可选项，是夹具必须与真实摄取产物同形的一部分。
        doc_entities: dict[str, list[str]] = {d["doc_id"]: [] for d in DOCS}
        doc_relations: dict[str, list[list[str]]] = {d["doc_id"]: [] for d in DOCS}
        entity_chunks: dict[str, dict] = {}
        relation_chunks: dict[str, dict] = {}

        for name, _etype, _desc, chunk_ids in ENTITIES:
            entity_chunks[name] = {
                "chunk_ids": list(chunk_ids),
                "count": len(chunk_ids),
                "updated_at": _now(),
            }
            for cid in chunk_ids:
                doc_id = cid.rpartition("-chunk-")[0]
                if name not in doc_entities[doc_id]:
                    doc_entities[doc_id].append(name)

        for src, tgt, _desc, _kw in RELATIONS:
            src_chunks = [c for n, _t, _d, cs in ENTITIES if n == src for c in cs]
            tgt_chunks = [c for n, _t, _d, cs in ENTITIES if n == tgt for c in cs]
            shared = sorted(set(src_chunks) & set(tgt_chunks)) or list(src_chunks[:1])
            key = "<SEP>".join(sorted((src, tgt)))
            relation_chunks[key] = {
                "chunk_ids": shared,
                "count": len(shared),
                "updated_at": _now(),
            }
            for cid in shared:
                doc_id = cid.rpartition("-chunk-")[0]
                pair = [src, tgt]
                if pair not in doc_relations[doc_id]:
                    doc_relations[doc_id].append(pair)

        await rag.full_entities.upsert(
            {
                doc_id: {"entity_names": sorted(names), "count": len(names)}
                for doc_id, names in doc_entities.items()
            }
        )
        await rag.full_relations.upsert(
            {
                doc_id: {"relation_pairs": pairs, "count": len(pairs)}
                for doc_id, pairs in doc_relations.items()
            }
        )
        if getattr(rag, "entity_chunks", None) is not None:
            await rag.entity_chunks.upsert(entity_chunks)
        if getattr(rag, "relation_chunks", None) is not None:
            await rag.relation_chunks.upsert(relation_chunks)

        # ---- 向量（只用 embedding，不碰 chat 模型）----
        await rag.entities_vdb.upsert(
            {
                name: {
                    "content": f"{name}\n{desc}",
                    "entity_name": name,
                    "source_id": "<SEP>".join(chunk_ids),
                    "file_path": _chunk_text(chunk_ids[0])[1],
                }
                for name, _etype, desc, chunk_ids in ENTITIES
            }
        )
        rels_vdb = getattr(rag, "relationships_vdb", None)
        if rels_vdb is not None:
            await rels_vdb.upsert(
                {
                    f"{src}<SEP>{tgt}": {
                        "content": f"{src}\t{tgt}\n{desc}",
                        "src_id": src,
                        "tgt_id": tgt,
                        "keywords": kw,
                        "file_path": "manual_creation",
                    }
                    for src, tgt, desc, kw in RELATIONS
                }
            )
        await rag.chunks_vdb.upsert(
            {
                c["chunk_id"]: {
                    "content": c["text"],
                    "full_doc_id": c["doc_id"],
                    "file_path": c["title"],
                }
                for c in chunks
            }
        )

        # 把每个存储自己落盘。这一步是必需的：`upsert` 只改内存（或只登记待嵌入），
        # 真正写文件挂在每个存储的 `index_done_callback` 上，而那个回调平时由
        # 摄取流水线调用——我们绕过了流水线（不要 LLM），就得自己叫一遍。
        await _flush_all(rag)
    finally:
        await rag.finalize_storages()

    return {
        "entities": [e[0] for e in ENTITIES],
        "relations": [{"source": r[0], "target": r[1]} for r in RELATIONS],
        "chunks": [c["chunk_id"] for c in chunks],
        "documents": [d["doc_id"] for d in DOCS],
    }


async def self_check(dir_path: Path) -> None:
    """建完当场验一遍：向量库真能召回、图真读得到、块真对得上 source_id。"""
    cfg = load_config()
    cfg.working_dir = str(dir_path)
    cfg.workspace = ""
    rag = await init_rag(cfg)
    try:
        hits = await rag.entities_vdb.query("张三在哪工作", top_k=3)
        print("  向量召回:", [h.get("entity_name") for h in hits])
        nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
        edges = await rag.chunk_entity_relation_graph.get_all_edges()
        print(f"  图: {len(nodes)} 节点 / {len(edges)} 边")
        chunk_ids = {c for n in nodes for c in str(n.get("source_id") or "").split("<SEP>") if c}
        missing = [c for c in chunk_ids if await rag.text_chunks.get_by_id(c) is None]
        print(f"  块: source_id 引用 {len(chunk_ids)} 个，取不到 {len(missing)} 个")
        assert hits, "向量召回为空：夹具的 embedding 没写进去"
        assert not missing, f"悬空 chunk 引用: {missing}"
    finally:
        await rag.finalize_storages()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 holdout 预置夹具（不需要 LLM）")
    parser.add_argument("--name", default="kb-small", help="夹具目录名")
    parser.add_argument("--keep-cache", action="store_true", help="保留 llm_response_cache")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="gkb-fixture-"))
    async def _run():
        manifest = await build(tmp)
        print("\n自检：")
        await self_check(tmp)
        return manifest

    try:
        manifest = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(f"!! 夹具生成失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    target = REPO_ROOT / "holdout" / "fixtures" / args.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in sorted(tmp.iterdir()):
        if not args.keep_cache and item.name.startswith(SKIP_PREFIXES):
            continue
        shutil.copy2(item, target / item.name)

    manifest["fixture"] = args.name
    manifest["generated_by"] = "scripts/make_holdout_fixtures.py"
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = sum(p.stat().st_size for p in target.iterdir())
    print(f"\n夹具 → {target}（{len(list(target.iterdir()))} 个文件，{total} 字节）")
    for p in sorted(target.iterdir()):
        print(f"  {p.name}  {p.stat().st_size}")
    print(f"  sha256(manifest) = {hashlib.sha256((target / 'manifest.json').read_bytes()).hexdigest()[:16]}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
