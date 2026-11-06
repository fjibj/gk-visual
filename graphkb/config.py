"""配置层：从环境变量（.env / 进程 env）读取，env 优先于默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class LLMConfig:
    provider: str = "anthropic"  # anthropic | openai_compat | ollama | mock
    model: str = "deepseek-v4-flash"
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 8192
    disable_thinking: bool = False


@dataclass
class EmbeddingConfig:
    provider: str = "ollama"  # ollama | openai_compat | mock
    model: str = "bge-m3"
    base_url: str = "http://localhost:11434"
    api_key: str = ""
    dim: int = 1024
    max_token_size: int = 8192


@dataclass
class RetrievalConfig:
    """检索命中分层的预算值（graphkb/query.py 用）。

    这三个数不是“调优参数”而是“防爆炸上限”：默认值经 S7 五轮实测选定，
    改它们不会改变判据（锚点/答案引用/最短路），只改变允许多宽。
    """

    hit_top_k: int = 5  # 向量召回规模：只用于兵底锚点 + 给候选打分，不决定谁进高亮
    max_hops: int = 4  # 锚点↔答案引用点之间最多连几跳；连不上就如实报「无路径」
    max_paths: int = 6  # 等长最短路最多展示几条（图上真有歧义时全显示，不静默挑一条）


@dataclass
class TriggerConfig:
    """harness 触发器的调度预算（M5）。

    `autonomous_limit` 不是判据，是「别话瘁」的调度上限：误触发只多花一次查询，
    漏触发只是维持现状。H0（显式点名）不受它限制。
    """

    autonomous_limit: int = 5


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    working_dir: str = "./data"
    language: str = "Chinese"
    workspace: str = ""
    max_upload_mb: int = 50


def load_config() -> Config:
    return Config(
        llm=LLMConfig(
            provider=_env("GKB_LLM_PROVIDER", "anthropic"),
            model=_env("GKB_LLM_MODEL", "deepseek-v4-flash"),
            base_url=_env("GKB_LLM_BASE_URL", ""),
            api_key=_env("GKB_LLM_API_KEY", ""),
            max_tokens=int(_env("GKB_LLM_MAX_TOKENS", "8192")),
            disable_thinking=_bool(_env("GKB_LLM_DISABLE_THINKING", "false")),
        ),
        embedding=EmbeddingConfig(
            provider=_env("GKB_EMBEDDING_PROVIDER", "ollama"),
            model=_env("GKB_EMBEDDING_MODEL", "bge-m3"),
            base_url=_env("GKB_EMBEDDING_BASE_URL", "http://localhost:11434"),
            api_key=_env("GKB_EMBEDDING_API_KEY", ""),
            dim=int(_env("GKB_EMBEDDING_DIM", "1024")),
            max_token_size=int(_env("GKB_EMBEDDING_MAX_TOKEN_SIZE", "8192")),
        ),
        retrieval=RetrievalConfig(
            hit_top_k=int(_env("GKB_HIT_TOP_K", "5")),
            max_hops=int(_env("GKB_MAX_HOPS", "4")),
            max_paths=int(_env("GKB_MAX_PATHS", "6")),
        ),
        triggers=TriggerConfig(autonomous_limit=int(_env("GKB_TRIGGER_K", "5"))),
        working_dir=_env("GKB_WORKING_DIR", "./data"),
        language=_env("GKB_LANGUAGE", "Chinese"),
        workspace=_env("GKB_WORKSPACE", ""),
        max_upload_mb=int(_env("GKB_MAX_UPLOAD_MB", "50")),
    )
