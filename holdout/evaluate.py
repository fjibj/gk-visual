"""判卷机：加载 holdout 场景，逐个执行，报告结果并写档。

纪律：
- 只读：不修改任何业务逻辑。
- 每轮一个版本标签（slice-1-v1、slice-1-v2…），失败轮次也存档。
- 场景派生自 expectations.md，不回看实现。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios" / "slice-1-doc-to-graph"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(REPO_ROOT))  # 让 graphkb 可导入
sys.path.insert(0, str(SCENARIOS_DIR))  # 让场景可 import _common

CATEGORIES = ["success", "failure", "boundary"]


def load_scenario(path: Path):
    spec = importlib.util.spec_from_file_location(f"scenario_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_one(mod) -> dict:
    try:
        passed, detail = asyncio.run(mod.run())
    except Exception as e:  # noqa: BLE001
        passed, detail = False, f"异常 {type(e).__name__}: {e}"
    return {"passed": passed, "detail": str(detail)}


def main() -> int:
    version = "slice-1-v1"
    version_dir = RESULTS_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for category in CATEGORIES:
        cat_dir = SCENARIOS_DIR / category
        if not cat_dir.is_dir():
            continue
        for path in sorted(cat_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod = load_scenario(path)
            outcome = run_one(mod)
            entry = {
                "category": category,
                "name": getattr(mod, "NAME", path.stem),
                "expectation": getattr(mod, "EXPECTATION", ""),
                "passed": outcome["passed"],
                "detail": outcome["detail"],
            }
            results.append(entry)
            mark = "PASS" if entry["passed"] else "FAIL"
            print(f"[{mark}] {category}/{entry['name']}: {entry['detail']}")

    n_pass = sum(1 for r in results if r["passed"])
    n_total = len(results)
    print(f"\n=== {n_pass}/{n_total} passed ===")

    report = {
        "version": version,
        "timestamp": datetime.now().isoformat(),
        "passed": n_pass,
        "total": n_total,
        "results": results,
    }
    report_path = version_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果已写入 {report_path}")

    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
