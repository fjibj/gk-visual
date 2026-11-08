"""现场验证：写入跑到一半被杀，重启后到底能不能查、能不能自愈（P7 任务票的依据）。

四段各跑一个独立进程（模拟 MCP 的 stdio 会话生命周期）：

    prepare <ws>            把 data/ 复制成实验库
    ingest  <ws>            起一次异步写入，然后挂着等被杀
    status  <ws> <job_id>   新进程：读落盘票据 + doc_status，看能不能查到
    resume  <ws>            新进程：写一篇新的小文档，看被中断那篇会不会被自动续跑

只做实验，不碰仓库里的 data/（它只把 data/ 复制一份当实验库）。

用法（四段各一个独立进程，模拟 MCP 的 stdio 会话生命周期）：
    python scripts/verify_job_resume.py prepare <实验库目录>
    python scripts/verify_job_resume.py ingest  <实验库目录>   # 起异步写入，然后挂着等被杀
    # 此时把上面那个进程杀掉（模拟会话结束），再：
    python scripts/verify_job_resume.py status  <实验库目录> <job_id>
    python scripts/verify_job_resume.py resume  <实验库目录>   # 另写一篇，看被中断那篇会不会被顺带续跑
"""
import asyncio
import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graphkb.config import load_config  # noqa: E402
from graphkb.memory_api import MemoryTools  # noqa: E402
from graphkb.rag import init_rag  # noqa: E402

TICKET = "mcp_jobs.json"


def _cfg(ws: str):
    import os

    os.environ["GKB_WORKING_DIR"] = ws
    os.environ["GKB_WORKSPACE"] = ""
    return load_config()


def _tickets(ws: str) -> dict:
    p = Path(ws) / TICKET
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("jobs", {})


def _dump_doc_status(rag) -> None:
    data = getattr(rag.doc_status, "_data", {}) or {}
    print(f"--- 盘上 doc_status：{len(data)} 条 ---")
    for doc_id, row in data.items():
        row = row if isinstance(row, dict) else getattr(row, "__dict__", {})
        print(
            f"  {doc_id}: status={row.get('status')!r} "
            f"file_path={row.get('file_path')!r} chunks={len(row.get('chunks_list') or [])} "
            f"updated={row.get('updated_at')}"
        )


async def prepare(ws: str) -> None:
    src = Path("data")
    dst = Path(ws)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"实验库就绪：{dst}（{len(list(dst.iterdir()))} 个文件）")


async def ingest(ws: str) -> None:
    rag = await init_rag(_cfg(ws))
    tools = MemoryTools(_cfg(ws), rag)
    import uuid

    tag = uuid.uuid4().hex[:6]  # 每次都新内容，免得吃 llm 缓存跑太快
    body = "\n\n".join(
        f"第{i}段（{tag}）：李四在银川做水利工程的验收记录，同行的是王五。"
        f"项目编号 YC-2026-{i:03d}，验收结论为暂缓，待补充施工日志、监理报告、材料合格证。"
        f"负责单位是{i}号监理站，联系人张某，电话不留。这一段只是用来把文档拉长成多块，"
        f"好让进程能被真正杀在中间。"
        for i in range(1, 7)
    )
    out = await tools.ingest(
        source="note",
        content=body,
        title=f"中断实验文档-{tag}",
        wait=False,
    )
    print("JOB", out["job_id"], flush=True)
    print("异步写入已发起，挂着等被杀（120s 后自杀）", flush=True)
    await asyncio.sleep(120)
    print("没被杀掉，自己退出（说明这次跑得比预期快）", flush=True)


async def status(ws: str, job_id: str) -> None:
    rag = await init_rag(_cfg(ws))
    tools = MemoryTools(_cfg(ws), rag)
    print("内存票据：", tools._jobs, "| 票据文件：", tools._jobs_path)
    print("落盘票据：", json.dumps(_tickets(ws), ensure_ascii=False, indent=1))
    out = await tools.ingest_status(job_id)
    print("ingest_status →", json.dumps(out, ensure_ascii=False, indent=1))
    _dump_doc_status(rag)
    await rag.finalize_storages()


async def resume(ws: str) -> None:
    rag = await init_rag(_cfg(ws))
    tools = MemoryTools(_cfg(ws), rag)
    print("=== 写一篇新的小文档，看被中断那篇会不会被顺带续跑 ===")
    out = await tools.ingest(
        source="note",
        content="续跑触发器：赵六在合肥负责设备选型，型号 HF-9，采购批次 2026-11。",
        title="续跑触发器文档",
        wait=True,
    )
    print("新文档写入 →", out["status"], out.get("error"))
    await asyncio.sleep(3)
    _dump_doc_status(rag)
    for job_id in _tickets(ws):
        st = await tools.ingest_status(job_id)
        print(f"票据 {job_id} → status={st['status']} doc_status={st.get('doc_status')} "
              f"source={st.get('status_source')}")
    await rag.finalize_storages()


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "prepare":
        asyncio.run(prepare(sys.argv[2]))
    elif cmd == "ingest":
        asyncio.run(ingest(sys.argv[2]))
    elif cmd == "status":
        asyncio.run(status(sys.argv[2], sys.argv[3]))
    elif cmd == "resume":
        asyncio.run(resume(sys.argv[2]))
    else:
        raise SystemExit(f"unknown cmd {cmd}")


main()
