#!/usr/bin/env python3
"""Baseline-4 funding_rate challenger scaffold (W24a).

Contract: docs/research/Candidate-Baseline-4.md

  - Same family as B3 (`funding_rate`) but **entry_threshold=0.0004**
  - Artifacts **only** under ``data/paper_replay/baseline4/``
  - **Never** writes into ``baseline3/`` or mutates B3 frozen YAML

Modes:

  --dry-run     write contract stub + adjudication DRAFT without full replay
  --synthetic   use synthetic OHLCV + synthetic funding for structure smoke
  (default)     attempt real parquet + meta (may BLOCKED/NARROWED like B3)

    python scripts/run_baseline4_challenger.py --dry-run
    python scripts/run_baseline4_challenger.py --synthetic --out-dir data/paper_replay/baseline4/smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig  # noqa: E402
from quantflow.strategy.research.contract_pin import (  # noqa: E402
    fingerprint_ohlcv,
    fingerprint_universe,
)
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)
from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    build_funding_tca,
)

OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline4"
FORBIDDEN_OUT = REPO_ROOT / "data" / "paper_replay" / "baseline3"
SYMBOL = "BTC/USDT"
# B4 locked params (must not equal silent B3 edit — new contract id)
B4_PARAMS: dict[str, Any] = {
    "entry_threshold": 0.0004,
    "exit_threshold": 0.00015,
    "oi_lookback": 3,
    "oi_change_threshold": 0.05,
}
B3_ENTRY = 0.001  # frozen reference only


def _assert_not_baseline3(out_dir: Path) -> None:
    resolved = out_dir.resolve()
    forbidden = FORBIDDEN_OUT.resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise SystemExit(
            f"[b4] REFUSED: out-dir {out_dir} collides with baseline3/ (W24a freeze discipline)"
        )
    if "baseline3" in resolved.parts:
        raise SystemExit(f"[b4] REFUSED: path contains baseline3 segment: {resolved}")


def _synthetic_ohlcv(n: int = 200, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50_000.0 + np.cumsum(rng.normal(0, 50, n))
    ts0 = 1_700_000_000_000
    return pd.DataFrame(
        {
            "timestamp": ts0 + np.arange(n) * 3_600_000,
            "open": close,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": rng.uniform(10, 100, n),
        }
    )


async def _replay_variant(
    strategy_name: str,
    df: pd.DataFrame,
    *,
    params: dict[str, Any] | None,
    fee: float,
    slip: float,
) -> dict[str, Any]:
    cfg = AppConfig(
        execution=ExecutionConfig(mode="paper", taker_fee=fee, slippage=slip),
        risk=RiskConfig(kill_switch_enabled=False, max_drawdown=-0.9),
    )
    sink = RecordingSink()
    session = build_session(
        strategy_name,
        capital=100_000.0,
        sink=sink,
        config=cfg,
        params=params,
        research_risk_bypass=True,
    )
    fills: list[dict[str, object]] = []
    risk_events: list[dict[str, object]] = []
    curve = await replay(session, df, SYMBOL, fills=fills, risk_events=risk_events)
    rep = aggregate(curve, fills, risk_events, sink.alerts, 100_000.0, entry_tf="1h")
    return {
        "n_fills": len(fills),
        "final_equity": float(curve[-1]["equity"]) if curve else 100_000.0,
        "sharpe_annualized": rep.get("sharpe_annualized"),
        "total_return_pct": rep.get("total_return_pct"),
        "max_drawdown_pct": rep.get("max_drawdown_pct"),
    }


def _write_package(
    out_dir: Path,
    *,
    mode: str,
    status: str,
    notes: list[str],
    results: dict[str, Any],
    df: pd.DataFrame | None,
) -> dict[str, Any]:
    _assert_not_baseline3(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).isoformat()
    fp: dict[str, Any] = {}
    if df is not None and not df.empty:
        fp = fingerprint_universe({SYMBOL: df})
        fp["ohlcv"] = fingerprint_ohlcv(df)

    adjudication = {
        "contract_id": "B4",
        "status": status,
        "verdict": "DRAFT" if status in ("DRY_RUN", "SYNTHETIC_SMOKE") else status,
        "promotion": "KEEP_BASELINE_0",  # default; never auto UPGRADE
        "b3_frozen_entry_threshold": B3_ENTRY,
        "b4_entry_threshold": B4_PARAMS["entry_threshold"],
        "notes": notes,
        "created_at": created,
        "rule": "B4 must not overwrite baseline3 or funding_rate.yaml defaults",
    }
    run_meta = {
        "contract_id": "B4",
        "execution_path": "paper_replay",
        "symbol": SYMBOL,
        "mode": mode,
        "params": B4_PARAMS,
        "data_fingerprint": fp,
        "results": results,
        "created_at": created,
        "promotion_eligible": False,
        "artifacts_root": str(out_dir).replace("\\", "/"),
    }
    funding_tca = build_funding_tca(
        mode="assumption",
        notes=f"B4 {mode} package structure",
    )
    (out_dir / "adjudication.json").write_text(
        json.dumps(adjudication, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (out_dir / "funding_tca.json").write_text(
        json.dumps(funding_tca, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "contract_id": "B4",
                "status": status,
                "out_dir": str(out_dir).replace("\\", "/"),
                "entry_threshold": B4_PARAMS["entry_threshold"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"adjudication": adjudication, "run_meta": run_meta, "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--out-dir",
        default=str(OUT_DIR.relative_to(REPO_ROOT)).replace("\\", "/"),
        help="Must be under baseline4/ (never baseline3/)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Write DRAFT package only")
    ap.add_argument(
        "--synthetic",
        action="store_true",
        help="Synthetic OHLCV smoke replay (structure only)",
    )
    ap.add_argument(
        "--meta-window",
        action="store_true",
        help="W25a: attempt real OHLCV+funding pin window (independent run_id under baseline4/)",
    )
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument(
        "--run-id",
        default=None,
        help="Subdir under out-dir for dated artifacts (default: UTC stamp)",
    )
    ap.add_argument(
        "--meta-root",
        action="append",
        default=None,
        help="Parquet root with meta_funding_rate (repeatable)",
    )
    ap.add_argument("--n-bars", type=int, default=120)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    # W25a: independent run_id so re-runs never overwrite sibling packages
    if args.meta_window or args.run_id:
        rid = args.run_id or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out_dir = out_dir / rid
    try:
        _assert_not_baseline3(out_dir)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2

    # Guard: B4 params must differ from frozen B3 entry
    if float(B4_PARAMS["entry_threshold"]) == float(B3_ENTRY):
        print("[b4] internal error: B4 entry equals B3 — abort", file=sys.stderr)
        return 2

    if args.dry_run:
        pkg = _write_package(
            out_dir,
            mode="dry_run",
            status="DRY_RUN",
            notes=[
                "W24a dry-run: no market data consumed",
                "B3 remains FROZEN KEEP_B0",
            ],
            results={},
            df=None,
        )
        print(json.dumps({"ok": True, **pkg["adjudication"], "out": pkg["out_dir"]}))
        return 0

    if args.meta_window:
        return _run_meta_window(args, out_dir)

    # Default path is synthetic smoke (safe for CI / no parquet).
    df = _synthetic_ohlcv(n=max(40, int(args.n_bars)))
    results: dict[str, Any] = {}
    try:
        results["classic"] = asyncio.run(
            _replay_variant("trend_following", df, params=None, fee=0.001, slip=0.001)
        )
        results["funding_rate_b4"] = asyncio.run(
            _replay_variant(
                "funding_rate",
                df,
                params=B4_PARAMS,
                fee=0.001,
                slip=0.001,
            )
        )
        status = "SYNTHETIC_SMOKE"
        notes = [
            "W24a synthetic smoke — not a sealed OOS adjudication",
            f"B4 entry_threshold={B4_PARAMS['entry_threshold']} (B3 frozen at {B3_ENTRY})",
        ]
    except Exception as e:
        status = "ERROR"
        notes = [f"synthetic replay error: {e}"]
        results = {"error": str(e)}

    pkg = _write_package(
        out_dir,
        mode="synthetic",
        status=status,
        notes=notes,
        results=results,
        df=df,
    )
    print(json.dumps({"ok": status != "ERROR", "status": status, "out": pkg["out_dir"]}))
    return 0 if status != "ERROR" else 1


def _run_meta_window(args: argparse.Namespace, out_dir: Path) -> int:
    """W25a: real pin-window attempt; BLOCKED/NARROWED/OK with independent run_id."""
    from quantflow.data.store import DataStore
    from quantflow.strategy.research.contract_pin import parse_window_ms

    notes: list[str] = [
        "W25a meta-window challenger scaffold",
        "Does not write baseline3/; does not mutate B3 YAML",
        f"B4 entry_threshold={B4_PARAMS['entry_threshold']} (B3 frozen {B3_ENTRY})",
    ]
    try:
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except Exception as e:
        print(f"[b4] pin error: {e}", file=sys.stderr)
        return 2

    meta_roots = (
        [Path(p) if Path(p).is_absolute() else REPO_ROOT / p for p in args.meta_root]
        if args.meta_root
        else [
            REPO_ROOT / "data" / "s3_verify" / "raw",
            REPO_ROOT / "data" / "parquet",
            REPO_ROOT / "data" / "meta_merged",
        ]
    )

    # OHLCV
    ohlcv_store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        raw = ohlcv_store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
    except Exception as e:
        raw = pd.DataFrame()
        notes.append(f"ohlcv query error: {e}")
    finally:
        ohlcv_store.close()

    # Funding via light meta scan (reuse B3 roots without importing B3 OUT_DIR)
    funding_n = 0
    funding_max_abs = 0.0
    for root in meta_roots:
        if not root.is_dir():
            notes.append(f"meta root missing: {root}")
            continue
        try:
            store = DataStore(str(root), ":memory:")
            try:
                f = store.query_funding_rates(SYMBOL, start=start_ms, end=end_ms)
            finally:
                store.close()
            if f is not None and not f.empty and "funding_rate" in f.columns:
                funding_n = max(funding_n, len(f))
                funding_max_abs = max(funding_max_abs, float(f["funding_rate"].abs().max()))
                notes.append(f"funding from {root.as_posix()} n={len(f)}")
        except Exception as e:
            notes.append(f"meta load skip {root}: {e}")

    status = "OK"
    block_reasons: list[str] = []
    if raw is None or raw.empty:
        status = "BLOCKED"
        block_reasons.append("no OHLCV in pin window")
    if funding_n < 24:
        status = "BLOCKED"
        block_reasons.append(f"funding points {funding_n} < 24")

    results: dict[str, Any] = {
        "funding_points": funding_n,
        "funding_max_abs": funding_max_abs,
        "ohlcv_bars": len(raw) if raw is not None else 0,
        "block_reasons": block_reasons,
    }

    df: pd.DataFrame | None = None
    if status != "BLOCKED" and raw is not None and not raw.empty:
        df = raw[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        # Cap bars for smoke-scale replay if huge
        if len(df) > 2000:
            df = df.iloc[-2000:].reset_index(drop=True)
            notes.append("ohlcv truncated to last 2000 bars for scaffold replay")
        try:
            results["classic"] = asyncio.run(
                _replay_variant("trend_following", df, params=None, fee=0.001, slip=0.001)
            )
            results["funding_rate_b4"] = asyncio.run(
                _replay_variant(
                    "funding_rate",
                    df,
                    params=B4_PARAMS,
                    fee=0.001,
                    slip=0.001,
                )
            )
            notes.append("meta-window paper_replay completed (not sealed UPGRADE)")
        except Exception as e:
            status = "ERROR"
            notes.append(f"replay error: {e}")
            results["error"] = str(e)
    else:
        notes.extend(block_reasons)

    # Still KEEP_B0 by default — human must upgrade
    pkg = _write_package(
        out_dir,
        mode="meta_window",
        status=status if status != "OK" else "META_SMOKE",
        notes=notes,
        results=results,
        df=df,
    )
    print(
        json.dumps(
            {
                "ok": status not in ("ERROR",),
                "status": status if status != "OK" else "META_SMOKE",
                "out": pkg["out_dir"],
                "funding_points": funding_n,
            }
        )
    )
    return 0 if status != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
