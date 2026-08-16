"""共享 harness：S6 文档生命周期考卷（真实 LLM + 真实 bge-m3）。

文档抽取是 LLM 的活，考卷必须用真实 LLM（火山）+ bge-m3（Ollama）。
文档上传/覆盖/删除复用 graphkb.documents，断言「文档→图→删除收敛」。
"""

from __future__ import annotations

import tempfile

from graphkb.config import load_config
from graphkb.documents import list_documents, upsert_document
from graphkb.rag import init_rag

SAMPLE1 = "张三是一位软件工程师，他居住在北京。张三于2020年加入了字节跳动公司，担任后端工程师。字节跳动的总部位于北京。字节跳动由张一鸣创立。张一鸣毕业于南开大学。"
SAMPLE2 = "李四是一名产品经理，他在北京工作。李四于2021年加入了字节跳动公司。字节跳动是一家互联网公司，总部位于北京。"
SAMPLE1_V2 = "张三是一位软件工程师，他居住在北京。张三于2020年加入了字节跳动公司，担任算法工程师。字节跳动的总部位于北京。"


def make_config(workdir):
    cfg = load_config()
    cfg.working_dir = str(workdir)
    # 唯一 workspace：隔离 LightRAG 全局存储缓存（doc_status 等按 workspace 命名空间），
    # 否则同进程顺序跑多个场景时会跨实例残留 doc 记录。
    import os
    cfg.workspace = f"s6-{os.path.basename(str(workdir))}"
    return cfg


async def build_rag(workdir):
    return await init_rag(make_config(workdir))


async def run_with_rag(fn):
    """构建真实 rag，执行 fn(rag) -> (passed, detail)，自动清理临时目录。"""
    td = tempfile.TemporaryDirectory()
    try:
        rag = await build_rag(td.name)
        result = await fn(rag)
        await rag.finalize_storages()
        return result
    finally:
        td.cleanup()
