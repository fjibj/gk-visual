"""LightRAG 封装：按配置构建并初始化实例。"""

from __future__ import annotations

from lightrag import LightRAG

from .config import Config
from .providers import build_embedding, build_llm


def build_rag(config: Config) -> LightRAG:
    return LightRAG(
        working_dir=config.working_dir,
        llm_model_func=build_llm(config),
        embedding_func=build_embedding(config),
        addon_params={"language": config.language},
    )


async def init_rag(config: Config) -> LightRAG:
    rag = build_rag(config)
    await rag.initialize_storages()
    return rag
