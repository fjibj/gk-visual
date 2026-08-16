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
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    working_dir: str = "./data"
    language: str = "Chinese"


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
        working_dir=_env("GKB_WORKING_DIR", "./data"),
        language=_env("GKB_LANGUAGE", "Chinese"),
    )
