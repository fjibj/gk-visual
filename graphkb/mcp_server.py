"""MCP 适配器（stdio）——Agent 记忆面，与 `server.py`（Web 人类面）并列、互不影响。

设计原则（《接口设计：Agent 记忆面》P1–P7）：
  · scope 启动时绑定：`graphkb-mcp --workspace ws-team-x`，工具参数里**永不出现**团队概念
  · 与人类面共用同一套 core（`query()` / `upsert_document()`），这里只做协议翻译
  · 日志一律走 stderr：stdout 是 JSON-RPC 的管道，混进一行日志客户端就崩

版本锁的依据（2026-11-04 实测定版，mcp 2.3.0）：
  · `mcp_types.version.HANDSHAKE_PROTOCOL_VERSIONS` 含 "2025-11-25"
  · 裸 JSON-RPC 探针：initialize(protocolVersion=2025-11-25) 原样回显、未降级
  · 工具名合规字符集含点号（SEP-986 `^[A-Za-z0-9._-]{1,128}$`），`memory.search` 合法
  · 2.x 把 `FastMCP` 改名 `MCPServer`（`mcp.server.fastmcp` 已删）
启动时会再自检一次：哪天 SDK 把 handshake 版协议撤了，这里先喊，而不是等 agent 调不通。
"""

# 刻意不写 `from __future__ import annotations`：
# MCPServer 用 get_type_hints 解析工具签名，而 `Context` 是在 build_server() 内部
# 延迟 import 的局部名。若注解被字符串化，解析时找不到 `Context` → InvalidSignature。
# 不要这个 future import，注解在函数定义那一刻就绑定成本地对象，两全（仍然不顶层 import mcp）。

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dotenv import load_dotenv

from .config import Config, load_config
from .memory_api import API_VERSION, MemoryTools
from .rag import init_rag

EXPECTED_PROTOCOL_VERSION = "2025-11-25"
"""Cola 侧实测报出的协议版本（探针 A）。不再支持 = 适配器失效，必须显式报错。"""


@dataclass
class ServerState:
    cfg: Config
    rag: object
    tools: MemoryTools


def _handshake_versions() -> tuple[str, ...]:
    """当前 SDK 支持「initialize 握手」的协议版本集合（2.x 与 1.x 的模块位置不同）。"""
    try:  # mcp 2.x：协议常量独立成包
        from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

        return tuple(HANDSHAKE_PROTOCOL_VERSIONS)
    except Exception:  # noqa: BLE001 — 1.x 布局，只为给出可读报错
        pass
    try:
        from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

        return tuple(SUPPORTED_PROTOCOL_VERSIONS)
    except Exception:  # noqa: BLE001
        return ()


def check_protocol_support() -> list[str]:
    """返回当前 SDK 缺失的协议版本；空列表 = 支持。"""
    versions = _handshake_versions()
    if not versions:
        return [EXPECTED_PROTOCOL_VERSION]
    return [] if EXPECTED_PROTOCOL_VERSION in versions else [EXPECTED_PROTOCOL_VERSION]


def build_server():
    """构造 MCP server（不启动）。rag 在 lifespan 里初始化/收尾，与 stdio 的事件循环同一个。"""
    from mcp.server import MCPServer
    from mcp.server.mcpserver import Context

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        cfg = load_config()  # workspace 已由 main() 写进 env，一起绑在这里
        rag = await init_rag(cfg)
        try:
            yield ServerState(cfg=cfg, rag=rag, tools=MemoryTools(cfg, rag))
        finally:
            await rag.finalize_storages()

    app = MCPServer(
        name="gk-visual",
        version=API_VERSION,
        instructions=(
            "gk-visual 的 Agent 记忆面。"
            "memory.search 检索：返回预算内的 answer_context（唯一建议注入上下文的内容）+ "
            "hits/trace（只用于审计与展示，别塞进 prompt）+ degraded/reason（据此决定信多少）。"
            "memory.ingest 写入：默认异步，回 job_id，用 memory.ingest_status 查进度。"
            "scope 在 server 启动时按 workspace 绑定，参数里没有团队/群/域。"
        ),
        lifespan=lifespan,
    )

    def _tools(ctx: Context) -> MemoryTools:
        return ctx.request_context.lifespan_context.tools

    @app.tool(name="memory.search")
    async def memory_search(
        ctx: Context,
        context: dict,
        budget: dict | None = None,
        mode: str = "agent",
        caller: str | None = None,
    ) -> dict:
        """检索记忆：锚点取 context.query，证据取 context.task。

        - context.task   必填。当前任务/计划文本 —— 它是「证据源」（人类面的「答案」替身）
        - context.query  可选。要检索的问题；缺省时 = task（此时证据层无法与锚点分离，
                         会退化成人类面语义并回 reason="texts_equal"）
        - budget         {top_k, max_hops, max_paths, max_context_tokens}
        - mode           agent（默认，不生成答案）| human（生成答案并以答案当证据）| auto
        - caller         仅记录，用于审计
        """
        return await _tools(ctx).search(context=context, budget=budget, mode=mode, caller=caller)

    @app.tool(name="memory.ingest")
    async def memory_ingest(
        ctx: Context,
        source: str,
        content: str,
        title: str | None = None,
        stable_id: str | None = None,
        origin: str = "extracted",
        wait: bool = False,
    ) -> dict:
        """写入记忆（默认异步，回 job_id 就走）。

        - source     doc | session | note
        - content    文本内容（文件解析由调用方或 Web 面上传端点负责）
        - title      可选标题；同标题 = 同文档（覆盖更新）
        - stable_id  可选稳定身份，作用同 title
        - origin     extracted | manual（M4 溯源标签用，现在只记录不生效）
        - wait       设计文档里的 `async: false`：等写完再返回（`async` 是 Python 关键字）
        """
        return await _tools(ctx).ingest(
            source=source,
            content=content,
            title=title,
            stable_id=stable_id,
            origin=origin,
            wait=wait,
        )

    @app.tool(name="memory.ingest_status")
    async def memory_ingest_status(ctx: Context, job_id: str) -> dict:
        """查 `memory.ingest` 的写入进度（queued | running | done | error | unknown）。"""
        return _tools(ctx).ingest_status(job_id=job_id)

    return app


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="graphkb-mcp", description="gk-visual Agent 记忆面（MCP over stdio）"
    )
    parser.add_argument(
        "--workspace",
        default="",
        help="绑定 workspace（启动时固定；工具参数里没有团队/群/域概念）",
    )
    args = parser.parse_args(argv)

    if args.workspace:
        os.environ["GKB_WORKSPACE"] = args.workspace

    # stdout 是 JSON-RPC 管道：日志与提示一律 stderr
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s"
    )

    missing = check_protocol_support()
    if missing:
        print(
            "graphkb-mcp: 当前 mcp SDK 不再支持协议 "
            f"{missing}（客户端握手会失败）。\n"
            '            固定装 pip install -e ".[mcp]"（mcp>=2.3.0,<3），或升级本适配器。',
            file=sys.stderr,
        )
        raise SystemExit(2)

    ws = os.environ.get("GKB_WORKSPACE") or "(默认 workspace)"
    print(
        f"graphkb-mcp: workspace={ws} transport=stdio protocol={EXPECTED_PROTOCOL_VERSION}",
        file=sys.stderr,
    )
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
