#!/usr/bin/env python3
"""One-shot assert for Elliott cost-grid packages (W25b).

Checks structure only:

  - execution_path + data_fingerprint (W14)
  - fee_slip_grid (zero + production cells)
  - funding_tca present

Does **not** register, promote, or flip decision to GO.

    python scripts/assert_elliott_cost_package.py --dir data/paper_replay/elliott_w23
    python scripts/assert_elliott_cost_package.py --build --n-bars 80 --reseat
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    CostFidelityError,
    assert_promotion_cost_ready,
    require_cost_grid,
    require_funding_tca,
)
from quantflow.strategy.validation.promotion_path import (  # noqa: E402
    PromotionPathError,
    assert_promotion_path_ready,
    check_promotion_path,
)


def _load_report(path: Path) -> dict[str, Any]:
    cost = path / "cost_report.json"
    meta = path / "run_meta.json"
    if cost.is_file():
        return json.loads(cost.read_text(encoding="utf-8"))
    if meta.is_file():
        meta_obj = json.loads(meta.read_text(encoding="utf-8"))
        # build minimal report from meta
        return {
            "execution_path": meta_obj.get("execution_path", "paper_replay"),
            "data_fingerprint": meta_obj.get("data_fingerprint"),
            "run_meta": meta_obj,
            "fee_slip_grid": meta_obj.get("fee_slip_grid"),
            "funding_tca": meta_obj.get("funding_tca"),
            "decision": meta_obj.get("decision", "NO_GO"),
        }
    raise FileNotFoundError(f"no cost_report.json or run_meta.json under {path}")


def assert_package_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return structured check result; raises on hard failure if assert_* used."""
    path_soft = check_promotion_path(report, require_fingerprint=True)
    cost_ok = True
    reasons: list[str] = []
    try:
        require_cost_grid(report)
    except CostFidelityError as e:
        cost_ok = False
        reasons.append(str(e))
    try:
        require_funding_tca(report)
    except CostFidelityError as e:
        cost_ok = False
        reasons.append(str(e))

    # Full gate (path + cost + funding) — same as register path structure
    full_ok = True
    full_err: str | None = None
    try:
        assert_promotion_path_ready(report, require_fingerprint=True)
        assert_promotion_cost_ready(
            report,
            require_funding=True,
            require_execution_path=True,
            require_fingerprint=True,
        )
    except (PromotionPathError, CostFidelityError, ValueError) as e:
        full_ok = False
        full_err = str(e)

    return {
        "path_check": path_soft,
        "cost_structure_ok": cost_ok,
        "cost_reasons": reasons,
        "full_register_structure_ok": full_ok,
        "full_error": full_err,
        "promotion_eligible_claim": report.get("promotion_eligible"),
        "decision": report.get("decision"),
        "note": ("Structure pass ≠ GO. Human adjudication + streak still required."),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=str, default=None, help="Package directory")
    ap.add_argument("--build", action="store_true", help="Build synthetic package first")
    ap.add_argument("--n-bars", type=int, default=80)
    ap.add_argument("--reseat", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument(
        "--require-full",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit 1 if full register structure fails",
    )
    args = ap.parse_args(argv)

    report: dict[str, Any]
    if args.build:
        from quantflow.strategy.research.elliott_cost_grid_contract import (
            build_elliott_cost_grid_package,
        )

        out = (
            Path(args.dir)
            if args.dir
            else REPO_ROOT / "data" / "paper_replay" / "elliott_assert_tmp"
        )
        pkg = asyncio.run(
            build_elliott_cost_grid_package(
                n_bars=args.n_bars,
                reseat=bool(args.reseat),
                output_dir=out,
            )
        )
        report = pkg.report
        print(f"[assert] built package under {out}", file=sys.stderr)
    else:
        if not args.dir:
            print("--dir required unless --build", file=sys.stderr)
            return 2
        report = _load_report(Path(args.dir))

    result = assert_package_report(report)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.require_full and not result["full_register_structure_ok"]:
        return 1
    if not result["path_check"].get("passed") or not result["cost_structure_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
