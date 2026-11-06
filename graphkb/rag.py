"""LightRAG 封装：按配置构建并初始化实例。"""

from __future__ import annotations

import logging
import os

from lightrag import LightRAG

from .config import Config
from .providers import build_embedding, build_llm

logger = logging.getLogger(__name__)

_WORKSPACE_OWNER: dict[str, str] = {}
"""workspace → 本进程里第一个绑定它的 working_dir（绝对路径）。

为什么要记这个：LightRAG 把 KV 数据挂在**进程级**共享字典 `_shared_dicts[workspace:namespace]`
上，而“谁负责从磁盘加载”只是个全局初始化标志。后果——同一进程里**同 workspace、不同
working_dir** 的第二个实例，`text_chunks` / `full_docs` 这类 KV 会直接是空的，不报错：
图还读得到（GraphML 是每个实例自己读文件），块却全查不到。真图回归就是被这个坑蹲到的：
前面用过的实例把 `:text_chunks` 初始化成它那份，后面指向真库的实例拿到的块是 0 条。
这里不悄悄绕过（绕过就等于把“数据没了”变成“数据在这儿其实没有”），只把坑喊出来。
"""


def _warn_if_workspace_shared(config: Config) -> None:
    key = str(config.workspace or "")
    here = os.path.abspath(str(config.working_dir))
    owner = _WORKSPACE_OWNER.setdefault(key, here)
    if owner != here:
        logger.warning(
            "同一进程里的另一个实例已经绑定了 workspace=%r（working_dir=%s），"
            "现在又要用 %s：LightRAG 的 KV 存储按 workspace 挂在进程级共享字典上，"
            "后者会拿到空的 text_chunks/full_docs（图能读，块读不到）。"
            "同时开多个库请给每个实例不同的 workspace（文件方在 <working_dir>/<workspace>/ 下），"
            "或拆成两个进程。",
            key,
            owner,
            here,
        )


def build_rag(config: Config) -> LightRAG:
    _warn_if_workspace_shared(config)
    return LightRAG(
        working_dir=config.working_dir,
        workspace=config.workspace,
        llm_model_func=build_llm(config),
        embedding_func=build_embedding(config),
        addon_params={"language": config.language},
    )


async def init_rag(config: Config) -> LightRAG:
    rag = build_rag(config)
    await rag.initialize_storages()
    return rag
