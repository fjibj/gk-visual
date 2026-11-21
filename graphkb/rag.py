"""LightRAG 封装：按配置构建、初始化实例，并处理「同进程多个库」这个坑。

## 为什么需要 `_isolate_shared_kv`

LightRAG 把 KV 数据挂在**进程级**共享字典 `_shared_dicts[workspace:namespace]` 上，
而「谁负责从磁盘加载」只是全局初始化标志（`shared_storage.try_initialize_namespace`）：
第一个调用者读自己的 JSON 文件填进去，后来者看到标志就**跳过读文件**。

后果：同一进程里两个实例、`workspace` 相同而 `working_dir` 不同时，
后者的 `text_chunks` / `full_docs` 直接是空的——不报错。图还读得到（GraphML 每个实例
自己读文件），所以现象很诱人：图文都对得上，块全查不到（`memory.expand` 一律 `missing`）。
2026-11-06 的真图回归就是被这个蹲到的：单独跑一个测试文件全绿，跑整套却红。

处置不是绕开，而是**按内容判定**：把我的磁盘文件读出来，若共享字典里缺我文件中的键，
说明那份共享数据不属于我，于是把 `_data` 换成本实例自己的字典——读自己的文件，
写也只落自己的目录。反过来，若共享字典已经包含我文件里的全部键（同一个库重复建实例），
就不动它，保持上游的共享语义。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from lightrag import LightRAG

from .config import Config
from .providers import build_embedding, build_llm

logger = logging.getLogger(__name__)

KV_STORAGES: tuple[str, ...] = (
    "text_chunks",
    "full_docs",
    "full_entities",
    "full_relations",
    "entity_chunks",
    "relation_chunks",
    "llm_response_cache",
    "doc_status",
)
"""LightRAG 上那些 `JsonKVStorage` 背书的属性（它们才有 `_file_name` / `_data`）。"""


def _load_json_file(path: str) -> dict:
    try:
        from lightrag.kg.json_kv_impl import load_json  # 上游自己的加载器，优先用它

        return load_json(path) or {}
    except Exception:  # noqa: BLE001 — 上游改了内部结构也不该让建实例失败
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh) or {}
        except Exception:  # noqa: BLE001
            return {}


def _isolate_shared_kv(rag: LightRAG) -> list[str]:
    """发现「进程级共享字典里的不是我的数据」时，把本实例的 KV 脱钩成私有副本。

    返回被隔离的存储名（空列表 = 没有冲突，什么都没动）。
    """
    isolated: list[str] = []
    for attr in KV_STORAGES:
        storage = getattr(rag, attr, None)
        path = getattr(storage, "_file_name", None)
        data = getattr(storage, "_data", None)
        if not path or data is None or not os.path.isfile(path):
            continue
        mine = _load_json_file(path)
        if not mine:
            continue
        if not (set(mine) - set(data)):
            # 共享字典里已经有我这份数据（同一个库重复建实例，或我本来就是第一个）——不动
            continue
        try:
            storage._data = mine  # noqa: SLF001 — 见模块 docstring：这是有意的脱钩
        except Exception as exc:  # noqa: BLE001
            logger.warning("KV 脱钩失败（%s）：%s: %s", attr, type(exc).__name__, exc)
            continue
        isolated.append(attr)
    return isolated


def build_rag(config: Config) -> LightRAG:
    return LightRAG(
        working_dir=config.working_dir,
        workspace=config.workspace,
        llm_model_func=build_llm(config),
        embedding_func=build_embedding(config),
        addon_params={"language": config.language},
    )


def _clear_shared_namespaces(workspace: str) -> list[str]:
    """把本 workspace 挂在进程级共享字典里的数据清掉（`reset_rag` 用）。

    要清三处，少一处重置就不干净：
      · `_shared_dicts`  —— 真数据；
      · `_init_flags`    —— 「已有人从磁盘加载过」的标志。留着它，新实例会跳过读文件，
        而共享字典刚被清空 —— 结果是空库，但看起来像加载成功；
      · `_namespace_data_cache` —— 每个 namespace 的字典对象缓存（1.5.7 为了少拿锁加的）。
        只删 `_shared_dicts` 的话，新实例会从缓存里拿回**同一个旧字典对象**：
        图会清空（图不走共享字典），文档与块却还在——2026-11-21 的重置验证就是这么红的。
    """
    try:
        from lightrag.kg import shared_storage  # 上游内部模块，拿不到就算了
    except Exception:  # noqa: BLE001
        return []
    prefix = f"{workspace}:" if workspace else ""
    cleared: list[str] = []
    for attr in ("_shared_dicts", "_init_flags", "_namespace_data_cache"):
        bucket = getattr(shared_storage, attr, None)
        if not isinstance(bucket, dict):
            continue
        for key in list(bucket.keys()):
            key_s = str(key)
            # 缓存里的键是 final namespace（有 workspace 时带前缀），与另两个一致
            if not prefix or key_s.startswith(prefix):
                try:
                    del bucket[key]
                except Exception:  # noqa: BLE001
                    continue
                cleared.append(f"{attr}:{key_s}")
    return cleared


def _wipe_dir(directory: str) -> None:
    """清空库目录（保留目录本身）。"""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


async def reset_rag(rag: LightRAG | None, config: Config, fixture_dir: Path | None = None) -> LightRAG:
    """**仅测试用**：清空库 → （可选）铺入预置夹具 → 重建实例。

    为什么不能只删文件：LightRAG 的 KV 数据挂在进程级字典上，删了磁盘文件
    内存里还在，新实例看到初始化标志就跳过读盘 —— 会得到一个「看起来空、
    实际还带着上个场景实体」的库。这种污染极难排查，所以顺序必须是
    先清共享字典，再删文件，再铺夹具，最后重建。
    """
    if rag is not None:
        try:
            await rag.finalize_storages()
        except Exception as exc:  # noqa: BLE001 — 收尾失败不该挡住重置
            logger.warning("重置前 finalize_storages 失败（继续）：%s: %s", type(exc).__name__, exc)
    cleared = _clear_shared_namespaces(config.workspace)
    if cleared:
        logger.info("reset：清掉进程级共享命名空间 %s", ", ".join(cleared))
    _wipe_dir(config.working_dir)
    if fixture_dir is not None:
        for item in Path(fixture_dir).iterdir():
            target = Path(config.working_dir) / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    return await init_rag(config)


async def init_rag(config: Config) -> LightRAG:
    rag = build_rag(config)
    await rag.initialize_storages()
    isolated = _isolate_shared_kv(rag)
    if isolated:
        logger.info(
            "workspace=%r 在进程内已被另一个库占用（%s）：%d 个 KV 存储改用本实例自己的数据副本。"
            "要彻底避免，给每个库不同的 GKB_WORKSPACE。",
            config.workspace or "",
            os.path.abspath(str(config.working_dir)),
            len(isolated),
        )
    return rag
