"""验证判卷机的重置隔离：建 A → 重置 → 查 A 必须为空。

这是手册 §3.3 与陷阱 #3 点名的那件事：reset 不彻底时，上一个场景的实体会在下个场景
被召回，而这种污染极难排查（图看着清空了，向量库或进程级 KV 里还留着）。

脚本自己拉起一个 `GKB_TEST_MODE=1` 的服务（独立临时库、不用你的 `data/`），四步跑完就关：

    python scripts/verify_holdout_reset.py [--fixture kb-small] [--port 8799]

只用图/文档/重置端点，**不需要 chat 模型**（所以没有 LLM 订阅也能跑）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _post(url: str, payload: dict | None = None, timeout: float = 120) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: float = 60) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_ready(base: str, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _get(f"{base}/api/health", timeout=5).get("status") == "ok":
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError(f"服务 {timeout}s 内没起来：{base}")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 holdout 重置隔离")
    parser.add_argument("--fixture", default="kb-small")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    work = Path(tempfile.mkdtemp(prefix="gkb-resetcheck-"))
    env = {
        **os.environ,
        "GKB_TEST_MODE": "1",
        "GKB_WORKING_DIR": str(work),
        "GKB_WORKSPACE": "",
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "graphkb.server:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    failures: list[str] = []
    try:
        wait_ready(base)
        print(f"服务就绪：{base}（库目录 {work}）\n")

        print("[1] 铺夹具")
        r1 = _post(f"{base}/api/_test/reset", {"fixture": args.fixture})
        print(f"    nodes={r1['nodes']} edges={r1['edges']} fixture={r1['fixture']}")
        s1 = _get(f"{base}/api/_test/state")
        print(f"    state: nodes={s1['nodes']} docs={len(s1['documents'])}")
        if r1["nodes"] <= 0:
            failures.append("铺夹具后图是空的：夹具本身有问题")

        print("\n[2] 重置（不带夹具）")
        r2 = _post(f"{base}/api/_test/reset", {})
        print(f"    nodes={r2['nodes']} edges={r2['edges']}")
        s2 = _get(f"{base}/api/_test/state")
        print(f"    state: nodes={s2['nodes']} docs={len(s2['documents'])}")
        if s2["nodes"] != 0:
            failures.append(f"重置后图里还有 {s2['nodes']} 个节点：上一个场景会污染下一个")
        if s2["documents"]:
            failures.append(f"重置后文档还在：{s2['documents']}")

        print("\n[3] 再铺一次（验证清空是「能重新加载」而不是「卡死」）")
        r3 = _post(f"{base}/api/_test/reset", {"fixture": args.fixture})
        print(f"    nodes={r3['nodes']} edges={r3['edges']}")
        if r3["nodes"] != r1["nodes"]:
            failures.append(
                f"重铺后节点数不一致：{r3['nodes']} vs {r1['nodes']}"
                "（进程级 KV / 向量没被真正清掉）"
            )

        print("\n[4] 空夹具库上读图（不该报错）")
        r4 = _post(f"{base}/api/_test/reset", {})
        g = _get(f"{base}/api/graph")
        print(f"    nodes={len(g['nodes'])} edges={len(g['edges'])}")
        if g["nodes"] or g["edges"]:
            failures.append("空库读图仍有内容")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n" + "=" * 56)
    if failures:
        print("FAIL")
        for f in failures:
            print(f"  · {f}")
        return 1
    print("PASS  重置隔离通过（建 A → 重置 → 查 A 为空；重铺可重新加载）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
