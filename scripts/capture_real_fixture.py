"""把一张真实 workspace 录成可离线复算的测试夹具（tests/fixtures/realgraph/）。

为什么要录而不是让测试直接连真库：
· CI 里没有那张图、没有 Ollama、也没有 key；
· 真图会变（增删文档），断言跟着漂就失去回归意义；
· 录下来的东西**只保留结构 + 一次真实检索的原样返回**，测试里零网络、零 LLM、可复算。

录什么：
· 一张裁剪过的 graphml（从真实图里按需 BFS 出来，保留 <SEP> 拼接的原始描述）；
· 每个 case 的 `aquery_data` 原样返回 + `entities_vdb.query` 原样返回；
· manifest.json（来源、时间、图规模、每个 case 的锚/证据文本）。

**默认脱敏**：这个仓库是公开的，真实图里是从我的设计文档抽出来的句子（含项目名、路线代号）。
所以夹具落盘前会把实体名与文本换成等长的填充文本，只保留**结构特征**——
节点数、度数分布、`<SEP>` 分段数、每段长度、带点号的方法名、连通分量规模都不变，
预算/token 估算据此复算一致。本地想留原始副本用 `--raw`（别提交）。

跑法（需要真实 workspace + Ollama，脚本自己拷一份临时库，不碰原件）：

    python scripts/capture_real_fixture.py \
        --workspace "C:/Users/fjibj/cola/outputs/gk-probe/probe-data" \
        --out tests/fixtures/realgraph

夹具重新录制后 `tests/test_real_graph.py` 会自动用新夹具；断言是结构性的（不锁具体分数），
所以换一份真实语料也能跑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import networkx as nx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from graphkb.config import load_config  # noqa: E402
from graphkb.rag import init_rag  # noqa: E402

GRAPH_FILE = "graph_chunk_entity_relation.graphml"

# 三个 case 各压一条通路：起手查（多锚点）、点名（单锚点 + 任务文本）
CASES = [
    {
        "name": "h1_plan",
        "question": "触发器 无感记忆 memory.search harness",
        "anchor_text": "触发器 无感记忆 memory.search harness",
        "evidence_text": "帮我整理触发器的设计，重点核对无感记忆和 memory.search 的预算，写进 harness 的说明",
    },
    {
        "name": "h0_named",
        "question": "触发器 无感记忆",
        "anchor_text": "触发器 无感记忆",
        "evidence_text": "触发器跟无感记忆是什么关系？",
    },
]

FILLER = "该条目记录了一项与整体方案相关的要点说明，供后续复盘查阅。"


# ---------------------------------------------------------------- 脱敏


def _filler(n_chars: int) -> str:
    """等长填充：保 token 量级（CJK 一字 ≈ 1 token），换掉真内容。"""
    if n_chars <= 0:
        return ""
    out = FILLER * (n_chars // len(FILLER) + 1)
    return out[:n_chars]


def _reskin(text: str) -> str:
    """保留 `<SEP>` 分段结构与每段长度，替换每段文字。"""
    if not text:
        return text
    segs = str(text).split("<SEP>")
    return "<SEP>".join(_filler(max(2, len(s.strip()))) for s in segs)


def _name_map(names) -> dict[str, str]:
    """实体名映射：带点号的名字保留点号（那是真实的命名形态），全 ASCII 的保留 ASCII。"""
    mapping: dict[str, str] = {}
    for i, name in enumerate(sorted(set(names))):
        if "." in name:
            mapped = ".".join(f"part{j + 1}" for j in range(name.count(".") + 1)) + f"_{i:02d}"
        elif all(ord(ch) < 128 for ch in name):
            mapped = f"symbol_{i:02d}"
        else:
            mapped = f"条目{i:02d}"
        mapping[name] = mapped
    return mapping


def _sanitize_graph(graph: nx.Graph) -> nx.Graph:
    mapping = _name_map([str(n) for n in graph.nodes])
    out = nx.relabel_nodes(graph, mapping)
    for _n, attrs in out.nodes(data=True):
        if attrs.get("description"):
            attrs["description"] = _reskin(str(attrs["description"]))
    for _u, _v, attrs in out.edges(data=True):
        for key in ("description", "keywords"):
            if attrs.get(key):
                attrs[key] = _reskin(str(attrs[key]))
    return out


def _sanitize_payload(payload, mapping: dict[str, str], doc_index: dict[str, str]):
    """把 aquery_data / vdb 的原样返回按同样的映射洗一遍（结构、顺序、字段全不动）。"""
    if isinstance(payload, str):
        return mapping.get(payload, payload)  # keywords 这类列表里的裸字符串
    if isinstance(payload, list):
        return [_sanitize_payload(x, mapping, doc_index) for x in payload]
    if not isinstance(payload, dict):
        return payload
    out = {}
    for key, value in payload.items():
        if key in ("entity_name", "id", "src_id", "tgt_id") and isinstance(value, str):
            out[key] = mapping.get(value, value)
        elif key in ("description", "keywords", "content") and isinstance(value, str):
            out[key] = _reskin(value)
        elif key == "file_path" and isinstance(value, str):
            out[key] = doc_index.setdefault(value, f"doc-{len(doc_index) + 1:02d}.md")
        elif key in ("entity_type", "source_id", "chunk_id", "full_doc_id") and isinstance(value, str):
            out[key] = value
        elif isinstance(value, str) and value in mapping:
            out[key] = mapping[value]  # metadata.keywords 这类“光看字段名看不出是实体名”的位置
        else:
            out[key] = _sanitize_payload(value, mapping, doc_index)
    return out


def _collect_names(payload, acc: set[str] | None = None) -> set[str]:
    """把检索返回里出现过的实体名全挖出来（它们不一定都在裁剪后的子图里）。"""
    acc = set() if acc is None else acc
    if isinstance(payload, list):
        for x in payload:
            _collect_names(x, acc)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if key in ("entity_name", "id", "src_id", "tgt_id") and isinstance(value, str) and value:
                acc.add(value)
            else:
                _collect_names(value, acc)
    return acc


def _reskin_text(text: str, mapping: dict[str, str]) -> str:
    """把一段文本里的实体名换掉（长的先换，避免「张三」先吃了「张三丰」）。"""
    for old in sorted(mapping, key=len, reverse=True):
        if old and old in text:
            text = text.replace(old, mapping[old])
    return text


def _jsonable(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def _trim(graph: nx.Graph, seeds: list[str], max_nodes: int) -> nx.Graph:
    """从种子节点 BFS 出一个小一点的图：保住真实结构（含中间节点、<SEP> 描述）。"""
    keep: list[str] = []
    seen: set[str] = set()
    queue = [s for s in seeds if s in graph]
    while queue and len(keep) < max_nodes:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        keep.append(node)
        for nb in graph.neighbors(node):
            if nb not in seen:
                queue.append(nb)
    if not keep:  # 种子一个都没命中（换了语料）：退回按分量大小取
        for comp in sorted(nx.connected_components(graph), key=len, reverse=True):
            keep.extend(list(comp))
            if len(keep) >= max_nodes:
                break
        keep = keep[:max_nodes]
    return graph.subgraph(keep).copy()


async def main() -> int:
    parser = argparse.ArgumentParser(description="录制真实图测试夹具")
    parser.add_argument("--workspace", required=True, help="真实 workspace（脚本自己拷一份，不碰原件）")
    parser.add_argument("--out", default="tests/fixtures/realgraph", help="夹具输出目录")
    parser.add_argument("--max-nodes", type=int, default=80, help="裁剪后的节点上限")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="保留原始文本（只在本地用，别提交——仓库是公开的）",
    )
    args = parser.parse_args()

    load_dotenv()
    src = Path(args.workspace).resolve()
    if not (src / GRAPH_FILE).is_file():
        raise SystemExit(f"{src} 里没有 {GRAPH_FILE}，确认是 LightRAG workspace 吗")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="gkb_capture_"))
    ws = tmp / "ws"
    try:
        shutil.copytree(src, ws)  # 只读原件：LightRAG 初始化会碰库里的文件
        cfg = load_config()
        cfg.working_dir = str(ws)
        rag = await init_rag(cfg)
        try:
            from lightrag import QueryParam

            manifest_cases = []
            seeds: list[str] = []
            raw_payloads: dict[str, dict] = {}
            for case in CASES:
                param = QueryParam(mode="mix", top_k=cfg.retrieval.hit_top_k)
                data = _jsonable(await rag.aquery_data(case["question"], param))
                vdb = _jsonable(
                    await rag.entities_vdb.query(case["question"], top_k=cfg.retrieval.hit_top_k)
                )
                raw_payloads[case["name"]] = {"retrieval": data, "vdb": vdb}
                payload = data.get("data") or {}
                for e in payload.get("entities") or []:
                    name = e.get("entity_name") or e.get("id")
                    if name:
                        seeds.append(str(name))
                for r in payload.get("relationships") or []:
                    for key in ("src_id", "tgt_id"):
                        if r.get(key):
                            seeds.append(str(r[key]))
                manifest_cases.append(case)
                print(
                    f"  录好 case {case['name']}: entities={len(payload.get('entities') or [])} "
                    f"relations={len(payload.get('relationships') or [])}"
                )
        finally:
            await rag.finalize_storages()

        graph = nx.read_graphml(str(src / GRAPH_FILE))
        und = graph.to_undirected() if graph.is_directed() else graph
        sub = _trim(und, seeds, args.max_nodes)

        if args.raw:
            fixture_graph = sub
            payloads = raw_payloads
        else:
            # 洗图 + 洗检索结果必须用同一张名字表，否则回放时对不上；
            # 名字表要把「检索返回里有、但没进裁剪子图」的名字也包进来（否则那些会裸着落盘）。
            names = set(str(n) for n in graph.nodes)  # 全图：只出现在 case 文本里的实体名也要洗
            for payload in raw_payloads.values():
                for part in payload.values():
                    _collect_names(part, names)
            mapping = _name_map(names)
            fixture_graph = nx.relabel_nodes(sub, mapping)
            for _n, attrs in fixture_graph.nodes(data=True):
                # graphml 里节点名存了两处：<node id> 和 entity_id 属性；relabel 只管前者
                for key in ("entity_id", "id"):
                    if attrs.get(key) in mapping:
                        attrs[key] = mapping[attrs[key]]
                if attrs.get("description"):
                    attrs["description"] = _reskin(str(attrs["description"]))
            for _u, _v, attrs in fixture_graph.edges(data=True):
                for key in ("description", "keywords"):
                    if attrs.get(key):
                        attrs[key] = _reskin(str(attrs[key]))
            doc_index: dict[str, str] = {}
            payloads = {
                name: {
                    "retrieval": _sanitize_payload(payload["retrieval"], mapping, doc_index),
                    "vdb": _sanitize_payload(payload["vdb"], mapping, doc_index),
                }
                for name, payload in raw_payloads.items()
            }
            for case in manifest_cases:
                for key in ("question", "anchor_text", "evidence_text"):
                    case[key] = _reskin_text(case[key], mapping)

        for name, payload in payloads.items():
            (out / f"case_{name}.retrieval.json").write_text(
                json.dumps(payload["retrieval"], ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            (out / f"case_{name}.vdb.json").write_text(
                json.dumps(payload["vdb"], ensure_ascii=False, indent=1), encoding="utf-8"
            )
        nx.write_graphml(fixture_graph, str(out / GRAPH_FILE))

        comps = sorted(nx.connected_components(fixture_graph), key=len, reverse=True)
        no_desc = sum(
            1 for _n, d in fixture_graph.nodes(data=True) if not (d.get("description") or "").strip()
        )
        manifest = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "sanitized": not args.raw,
            "source_graph": {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "components": len(list(nx.connected_components(und))),
            },
            "fixture_graph": {
                "nodes": fixture_graph.number_of_nodes(),
                "edges": fixture_graph.number_of_edges(),
                "components": len(comps),
                "largest_component": len(comps[0]) if comps else 0,
                "nodes_without_description": no_desc,
            },
            "top_k": cfg.retrieval.hit_top_k,
            "cases": manifest_cases,
        }
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        total = sum(f.stat().st_size for f in out.iterdir())
        print(json.dumps(manifest["fixture_graph"], ensure_ascii=False))
        print(f"夹具已写入 {out}（{total / 1024:.0f} KB，sanitized={manifest['sanitized']}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
