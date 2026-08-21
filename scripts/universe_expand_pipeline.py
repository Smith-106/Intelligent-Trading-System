#!/usr/bin/env python3
"""Universe expansion pipeline (P2 T008).

For each candidate symbol:
  1) Data SLA — bar count, freshness, quality score (same weights as preflight)
  2) Optional shared-RP rebalance cost sensitivity (short window dry-run)

Does **not** mutate default.yaml or enable portfolio_optimization globally.
Outputs JSON under data/paper_replay/universe/.

Examples:
  python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,SOL/USDT
  python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,XRP/USDT --cost-days 90
  python scripts/universe_expand_pipeline.py --dry-run-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
MIN_BARS = 500
MAX_BAR_AGE_HOURS = 48.0
MIN_QUALITY = 0.7
OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "universe"


def _load_sla_thresholds() -> tuple[int, float, float]:
    """T019: thresholds from universe.yaml when present."""
    try:
        from quantflow.strategy.research.universe_config import load_universe_config

        cfg = load_universe_config(repo_root=REPO_ROOT)
        sla = cfg.get("sla") if isinstance(cfg.get("sla"), dict) else {}
        return (
            int(sla.get("min_bars", MIN_BARS)),
            float(sla.get("max_bar_age_hours", MAX_BAR_AGE_HOURS)),
            float(sla.get("min_quality", MIN_QUALITY)),
        )
    except Exception:
        return MIN_BARS, MAX_BAR_AGE_HOURS, MIN_QUALITY


def history_quality_score(df: Any, *, now_ms: int) -> float:
    """Composite 0–1 score: freshness / continuity / anomaly (static history)."""
    import pandas as pd

    if df is None or len(df) == 0:
        return 0.0
    ts = pd.to_numeric(df["timestamp"], errors="coerce").dropna().astype("int64")
    if ts.empty:
        return 0.0
    age_h = max(0.0, (now_ms - int(ts.max())) / 3_600_000.0)
    if age_h <= 24.0:
        freshness = 1.0
    elif age_h >= 96.0:
        freshness = 0.0
    else:
        freshness = max(0.0, 1.0 - (age_h - 24.0) / 72.0)

    ordered = ts.sort_values().to_numpy()
    if len(ordered) < 2:
        continuity = 0.5
    else:
        gaps = (ordered[1:] - ordered[:-1]) / 3_600_000.0
        ok = ((gaps >= 0.5) & (gaps <= 2.5)).sum()
        continuity = float(ok) / float(len(gaps))

    if "close" in df.columns and len(df) >= 3:
        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        rets = close.pct_change().dropna().abs()
        if rets.empty:
            anomaly = 1.0
        else:
            spike_rate = float((rets > 0.20).mean())
            anomaly = max(0.0, 1.0 - spike_rate * 5.0)
    else:
        anomaly = 0.8
    return freshness * 0.4 + continuity * 0.3 + anomaly * 0.3


def evaluate_symbol_sla(
    symbol: str,
    *,
    now_ms: int | None = None,
    min_bars: int | None = None,
    max_bar_age_hours: float | None = None,
    min_quality: float | None = None,
) -> dict[str, Any]:
    """Point-in-time data SLA for one symbol (1h bars)."""
    from quantflow.data.store import DataStore

    thr_bars, thr_age, thr_q = _load_sla_thresholds()
    min_bars = thr_bars if min_bars is None else int(min_bars)
    max_bar_age_hours = thr_age if max_bar_age_hours is None else float(max_bar_age_hours)
    min_quality = thr_q if min_quality is None else float(min_quality)

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        df = store.query(symbol, timeframe="1h")
    finally:
        store.close()

    n = len(df) if df is not None else 0
    if n == 0:
        return {
            "symbol": symbol,
            "bars": 0,
            "age_hours": None,
            "quality": 0.0,
            "sla_pass": False,
            "reasons": ["no_1h_bars"],
            "min_bars": min_bars,
            "max_bar_age_hours": max_bar_age_hours,
            "min_quality": min_quality,
        }

    ts_max = int(df["timestamp"].astype("int64").max())
    age_h = (now - ts_max) / 3_600_000.0
    quality = history_quality_score(df, now_ms=now)
    reasons: list[str] = []
    if n < min_bars:
        reasons.append(f"bars<{min_bars}")
    if age_h > max_bar_age_hours:
        reasons.append(f"age_h>{max_bar_age_hours}")
    if quality < min_quality:
        reasons.append(f"quality<{min_quality}")
    return {
        "symbol": symbol,
        "bars": n,
        "age_hours": round(age_h, 2),
        "quality": round(quality, 4),
        "last_ts": ts_max,
        "sla_pass": not reasons,
        "reasons": reasons,
        "min_bars": min_bars,
        "max_bar_age_hours": max_bar_age_hours,
        "min_quality": min_quality,
    }


def rebalance_cost_sensitivity(
    symbols: list[str],
    *,
    days: int = 90,
    fee: float = 0.001,
    slip: float = 0.001,
    rebalance_bars: int = 48,
) -> dict[str, Any]:
    """Short-window shared-book RP cost grid (fee×slip cells).

    Uses multi_symbol_replay building blocks when available; on failure returns
    structured error (fail-closed, no fake alpha).
    """
    import asyncio

    import pandas as pd

    from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig
    from quantflow.data.store import DataStore
    from quantflow.strategy.research.paper_replay import (
        RecordingSink,
        aggregate,
        build_multi_symbol_session,
        replay_multi,
    )

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    start_ms = end_ms - max(days, 7) * 86_400_000
    frames: dict[str, pd.DataFrame] = {}
    try:
        for sym in symbols:
            df = store.query(sym, start=start_ms, end=end_ms, timeframe="1h")
            if df.empty:
                continue
            frames[sym] = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(
                drop=True
            )
    finally:
        store.close()

    if len(frames) < 2:
        return {
            "ok": False,
            "error": "need ≥2 symbols with bars for shared RP sensitivity",
            "symbols_loaded": list(frames.keys()),
        }

    # Inner-join calendar
    common: set[int] | None = None
    for df in frames.values():
        ts = set(df["timestamp"].astype("int64").tolist())
        common = ts if common is None else (common & ts)
    if not common or len(common) < 100:
        return {
            "ok": False,
            "error": f"insufficient intersection bars ({0 if not common else len(common)})",
            "symbols_loaded": list(frames.keys()),
        }
    aligned: dict[str, pd.DataFrame] = {}
    for sym, df in frames.items():
        aligned[sym] = (
            df[df["timestamp"].astype("int64").isin(common)]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

    cells = [
        (0.0, 0.0),
        (fee, slip),
        (fee * 2, slip * 2),
    ]
    rows: list[dict[str, Any]] = []

    async def _one(taker: float, slippage: float) -> dict[str, Any]:
        from quantflow.common.config import PortfolioOptimizationConfig

        cfg = AppConfig(
            execution=ExecutionConfig(
                taker_fee=taker, maker_fee=taker * 0.8, slippage=slippage, mode="paper"
            ),
            risk=RiskConfig(
                portfolio_optimization=PortfolioOptimizationConfig(
                    enabled=True,
                    method="risk_parity",
                    level="symbol",
                    rebalance_every_n_bars=rebalance_bars,
                )
            ),
        )
        sink = RecordingSink()
        session = build_multi_symbol_session(
            "trend_following",
            list(aligned.keys()),
            capital=100_000.0,
            sink=sink,
            config=cfg,
            research_risk_bypass=True,
        )
        fills: list[dict[str, object]] = []
        risk_ev: list[dict[str, object]] = []
        curve = await replay_multi(
            session,
            aligned,
            fills,
            risk_ev,
            direction_gate=False,
            entry_tf="1h",
        )
        rep = aggregate(curve, fills, risk_ev, sink.alerts, 100_000.0, entry_tf="1h")
        return {
            "taker_fee": taker,
            "slippage": slippage,
            "return_pct": rep.get("return_pct"),
            "sharpe": rep.get("sharpe_annualized"),
            "max_drawdown_pct": rep.get("max_drawdown_pct"),
            "orders": rep.get("orders"),
        }

    for taker, slippage in cells:
        try:
            rows.append(asyncio.run(_one(taker, slippage)))
        except Exception as exc:
            rows.append(
                {
                    "taker_fee": taker,
                    "slippage": slippage,
                    "error": str(exc),
                }
            )

    zero = next((r for r in rows if r.get("taker_fee") == 0.0 and "error" not in r), None)
    base = next(
        (
            r
            for r in rows
            if r.get("taker_fee") == fee and r.get("slippage") == slip and "error" not in r
        ),
        None,
    )
    drag = None
    if zero and base and zero.get("return_pct") is not None and base.get("return_pct") is not None:
        drag = float(zero["return_pct"]) - float(base["return_pct"])

    return {
        "ok": True,
        "days": days,
        "symbols": list(aligned.keys()),
        "intersection_bars": len(common),
        "rebalance_every_n_bars": rebalance_bars,
        "fee_slip_grid": rows,
        "summary": {
            "cost_drag_pp": drag,
            "note": "Positive drag means zero-cost looks better than production fees",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--symbols",
        default="",
        help="Comma-separated candidates (default: universe.yaml candidates or Baseline-0 trio)",
    )
    ap.add_argument(
        "--from-config",
        action="store_true",
        help="T019: load candidates from quantflow/config/universe.yaml",
    )
    ap.add_argument(
        "--include-watchlist",
        action="store_true",
        help="With --from-config, also evaluate watchlist",
    )
    ap.add_argument(
        "--write-admitted",
        action="store_true",
        help="T019: write data/paper_replay/universe/admitted.json (SLA-pass only)",
    )
    ap.add_argument(
        "--cost-days",
        type=int,
        default=0,
        help="If >0, run shared-RP fee×slip sensitivity on last N days",
    )
    ap.add_argument(
        "--dry-run-only",
        action="store_true",
        help="Only evaluate SLA; skip cost sensitivity even if --cost-days set",
    )
    ap.add_argument(
        "--out",
        default="",
        help="Output JSON path (default data/paper_replay/universe/report_<ts>.json)",
    )
    args = ap.parse_args()

    symbols: list[str] = []
    config_path = None
    if args.from_config or not args.symbols:
        try:
            from quantflow.strategy.research.universe_config import (
                candidate_symbols,
                default_universe_path,
                load_universe_config,
            )

            cfg = load_universe_config(repo_root=REPO_ROOT)
            config_path = cfg.get("_path")
            if args.from_config or not args.symbols:
                symbols = candidate_symbols(
                    cfg,
                    include_watchlist=args.include_watchlist,
                    repo_root=REPO_ROOT,
                )
                print(f"[universe] from-config {default_universe_path(REPO_ROOT)} → {symbols}")
        except Exception as exc:
            print(f"[universe] config load failed: {exc}; using defaults", flush=True)
            symbols = list(DEFAULT_SYMBOLS)

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    if not symbols:
        print("no symbols", file=sys.stderr)
        return 2

    now_ms = int(time.time() * 1000)
    sla_rows = [evaluate_symbol_sla(s, now_ms=now_ms) for s in symbols]
    passed = [r for r in sla_rows if r["sla_pass"]]
    failed = [r for r in sla_rows if not r["sla_pass"]]
    admitted = [r["symbol"] for r in passed]

    print("Universe data SLA")
    for r in sla_rows:
        flag = "OK" if r["sla_pass"] else "FAIL"
        print(
            f"  [{flag}] {r['symbol']} bars={r['bars']} "
            f"age={r.get('age_hours')}h quality={r['quality']} "
            f"{','.join(r['reasons']) if r['reasons'] else ''}"
        )
    print(f"admitted (SLA pass): {admitted or '—'}")
    if failed:
        print(
            "NOT admitted (SLA fail → excluded from default baseline book): "
            + ", ".join(r["symbol"] for r in failed)
        )

    cost_block: dict[str, Any] | None = None
    if args.cost_days > 0 and not args.dry_run_only:
        # T019: cost grid only on SLA-pass symbols (never promote fail into RP book)
        cost_syms = admitted if admitted else []
        if not cost_syms:
            print("cost sensitivity skipped: no SLA-pass symbols")
            cost_block = {"ok": False, "error": "no_sla_pass_symbols"}
        else:
            print(f"Running cost sensitivity days={args.cost_days} symbols={cost_syms}")
            cost_block = rebalance_cost_sensitivity(cost_syms, days=args.cost_days)
            if cost_block.get("ok"):
                print(
                    f"  intersection_bars={cost_block.get('intersection_bars')} "
                    f"drag_pp={cost_block.get('summary', {}).get('cost_drag_pp')}"
                )
            else:
                print(f"  cost sensitivity skipped/failed: {cost_block.get('error')}")

    payload = {
        "kind": "universe_expand_report",
        "task": "T019",
        "generated_at": datetime.now(UTC).isoformat(),
        "config_path": config_path,
        "symbols": symbols,
        "admitted": admitted,
        "rejected": [r["symbol"] for r in failed],
        "sla": sla_rows,
        "sla_pass_count": len(passed),
        "sla_fail_count": len(failed),
        "cost_sensitivity": cost_block,
        "contract_notes": [
            "default.yaml portfolio_optimization.enabled stays false",
            "enable shared RP only via paper overlay / research scripts",
            "silo RP ≠ shared-book production claim",
            "attach fee_slip_grid before any GO narrative (P0 cost_fidelity)",
            "T019: SLA fail never enters admitted / default baseline book",
            "funding_tca required alongside fee×slip for GO (T014)",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = OUT_DIR / f"universe_report_{stamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = OUT_DIR / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"wrote {latest}")

    if args.write_admitted:
        from quantflow.strategy.research.universe_config import (
            baseline_default_symbols,
            write_admitted,
        )

        admitted_payload = {
            "kind": "universe_admitted",
            "task": "T019",
            "generated_at": payload["generated_at"],
            "symbols": admitted,
            "admitted": admitted,
            "rejected": payload["rejected"],
            "sla": sla_rows,
            "baseline_default": baseline_default_symbols(repo_root=REPO_ROOT),
            "baseline_book": [
                s for s in admitted if s in set(baseline_default_symbols(repo_root=REPO_ROOT))
            ],
            "rule": "Only sla_pass symbols; baseline runners use admitted ∩ baseline_default",
            "source_report": str(out_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        }
        adm_path = write_admitted(admitted_payload, repo_root=REPO_ROOT)
        print(f"wrote admitted {adm_path} → {admitted}")

    # Exit 1 if any SLA fail (usable in CI preflight for expanded universes)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
