"""签切片 / 打 tag / 发版之前的本地检查单（一条命令跑完，省得靠记性）。

为什么不在 CI 里跑全套：holdout 场景要**真 LLM + 真 embedding**，GitHub Actions 上
要么塞 key（这个仓库的安全底线是不放），要么跑不了。所以分工是——
  · CI（`.github/workflows/ci.yml`）：离线单元测试 + 真图回放 + 前端构建，每次 push 都跑；
  · 这里：需要网络/模型/真库的那些，签收之前在本机跑一遍。
历史上的教训：`_hit_trace` 改签名之后，S3 holdout 坏了 12 天没人发现——因为没人跑它。

用法：
    python scripts/preflight.py                    # 默认：离线测试 + 现场测试 + git 体检
    python scripts/preflight.py --holdout slice-8-document-ingestion-enhancement
    python scripts/preflight.py --skip-slow --skip-frontend
    python scripts/preflight.py --list             # 看有哪些切片可以跑 holdout

退出码：0 全过；1 有失败项（跳过不算失败，但会明说跳了什么）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT_DIR = ROOT / "holdout" / "scenarios"


def _run(name: str, argv: list[str], *, cwd: Path = ROOT, env: dict | None = None) -> dict:
    print(f"\n=== {name} ===")
    print("$ " + " ".join(argv))
    started = time.time()
    merged = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}
    proc = subprocess.run(argv, cwd=str(cwd), env=merged, text=True, encoding="utf-8",
                          errors="replace", capture_output=True)
    elapsed = time.time() - started
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-12:])
    if tail:
        print(tail)
    if proc.returncode != 0:
        err = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        if err:
            print("--- stderr（末 15 行）---")
            print(err)
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "elapsed": elapsed,
        "code": proc.returncode,
    }


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return (proc.stdout or "").strip()


def check_git() -> dict:
    """仓库体检：脏工作树、本地落后/领先后端、HEAD 是否已推。"""
    print("\n=== git 体检 ===")
    problems: list[str] = []
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head = _git("rev-parse", "--short", "HEAD")
    status = _git("status", "--porcelain")
    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    counts = _git("rev-list", "--left-right", "--count", f"{upstream}...HEAD") if upstream else ""

    print(f"branch={branch} HEAD={head} upstream={upstream or '(未设)'}")
    if status:
        problems.append(f"工作树不干净（{len(status.splitlines())} 个文件有改动）")
        print(status)
    if counts:
        behind, ahead = counts.split()
        print(f"落后 origin {behind} 个提交，领先 {ahead} 个")
        if ahead != "0":
            problems.append(f"有 {ahead} 个提交没推（签收前先 push，让 CI 跑一遍）")
    tags = _git("tag", "--points-at", "HEAD").split()
    print(f"HEAD 上的 tag：{tags or '无'}")
    for p in problems:
        print(f"  ! {p}")
    return {"name": "git 体检", "ok": not problems, "elapsed": 0.0, "code": 0 if not problems else 1,
            "notes": problems}


def _have_frontend() -> bool:
    return (ROOT / "frontend" / "package.json").is_file() and (ROOT / "frontend" / "node_modules").is_dir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preflight", description="签切片/打 tag 前的本地检查单")
    parser.add_argument("--holdout", action="append", default=[], metavar="SLICE",
                        help="要跑 holdout 的切片目录名（可重复）；留空则不跑")
    parser.add_argument("--holdout-version", default="", metavar="V",
                        help="holdout 结果版本标签（默认让 evaluate.py 自己取 -v1）；签收时建议用 tag 名")
    parser.add_argument("--skip-slow", action="store_true", help="跳过现场测试（需要真库副本 + 网络）")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过前端构建")
    parser.add_argument("--list", action="store_true", help="列出可跑的 holdout 切片后退出")
    args = parser.parse_args(argv)

    if args.list:
        for p in sorted(HOLDOUT_DIR.iterdir()):
            if p.is_dir():
                print(p.name)
        return 0

    results: list[dict] = [
        _run("离线测试（pytest -m 'not slow'）", [sys.executable, "-m", "pytest", "-q", "-m", "not slow"]),
    ]

    if args.skip_slow:
        print("\n跳过：现场测试（--skip-slow）")
    else:
        results.append(
            _run("现场测试（pytest -m slow：真库副本 + 真模型）",
                 [sys.executable, "-m", "pytest", "-q", "-m", "slow"])
        )

    for slice_id in args.holdout:
        if not (HOLDOUT_DIR / slice_id).is_dir():
            print(f"\n!! holdout 切片不存在：{slice_id}（用 --list 看看有哪些）")
            results.append({"name": f"holdout {slice_id}", "ok": False, "elapsed": 0.0, "code": 2})
            continue
        results.append(
            _run(f"holdout {slice_id}（真 LLM + 真 embedding）",
                 [sys.executable, "holdout/evaluate.py", slice_id]
                 + (["--version", args.holdout_version] if args.holdout_version else []))
        )

    if args.skip_frontend:
        print("\n跳过：前端构建（--skip-frontend）")
    elif _have_frontend():
        npx = "npm.cmd" if os.name == "nt" else "npm"
        results.append(_run("前端构建（tsc && vite build）", [npx, "run", "build"],
                            cwd=ROOT / "frontend"))
    else:
        print("\n跳过：前端构建（没装 node_modules，先 cd frontend && npm ci）")

    results.append(check_git())

    print("\n" + "=" * 60)
    failed = 0
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        failed += 0 if r["ok"] else 1
        print(f"{mark}  {r['name']}  ({r['elapsed']:.1f}s)")
    print("=" * 60)
    if failed:
        print(f"有 {failed} 项没过 —— 别签收，先看上面的输出。")
        return 1
    print("全过。可以签收 / 打 tag 了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
