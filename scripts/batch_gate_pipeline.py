#!/usr/bin/env python3
"""Batch cost/gate pipeline for multiple strategies (T015).

Default **fast** mode (recommended for nightly / day-session hook):
  - pin window (T011)
  - per strategy: fee×slip grid on vectorized backtest (0/0 + 0.1%/0.1%)
  - attach funding_tca (T014)
  - assert_promotion_cost_ready → pass / rejected

Optional ``--full-gate`` runs validation_gate (CPCV+DSR+WFO) — slow; not default.

Fail-closed aggregation: any candidate missing cost grid or funding_tca is
``rejected``. Overall exit code 0 only if every candidate is ``pass`` (or
``--allow-partial``).

    python scripts/batch_gate_pipeline.py --dry-run
    python scripts/batch_gate_pipeline.py --strategies trend_following,mean_reversion
    python scripts/batch_gate_pipeline.py --after-day-session
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.strategy.research.contract_pin import (  # noqa: E402
    ContractPinError,
    build_window_pin,
    parse_window_ms,
    warn_if_unpinned,
)
from quantflow.strategy.research.backtest import BacktestEngine  # noqa: E402
from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    CostFidelityError,
    assert_promotion_cost_ready,
    attach_cost_fidelity,
    build_funding_tca,
    summarize_measured_funding,
)

DEFAULT_STRATEGIES = (
    "trend_following",
    "mean_reversion",
    "volatility_breakout",
    "momentum_rotation",
)
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
SYMBOL = "BTC/USDT"
OUT_DEFAULT = "data/paper_replay/batch_gate/latest.json"
FEE_CELLS = ((0.0, 0.0), (0.001, 0.001))


def _load_bars(start_ms: int, end_ms: int) -> pd.DataFrame:
    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        df = store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df.empty:
        raise SystemExit(f"no {SYMBOL} 1h bars in pin window")
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(
        drop=True
    )


def _funding_block() -> dict[str, Any]:
    measured = None
    try:
        from quantflow.data.store import DataStore

        store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
        try:
            fdf = store.query_funding_rates("BTC-USDT-SWAP")
        finally:
            store.close()
        if fdf is not None and not fdf.empty and "funding_rate" in fdf.columns:
            rates = [float(x) for x in fdf["funding_rate"].tolist() if x == x]
            if rates:
                ts = fdf["timestamp"].astype("int64")
                measured = summarize_measured_funding(
                    rates,
                    symbol="BTC-USDT-SWAP",
                    start_ms=int(ts.min()),
                    end_ms=int(ts.max()),
                )
    except Exception:  # noqa: BLE001 — funding optional at load; assumption fallback
        measured = None
    return build_funding_tca(
        mode="hybrid" if measured else "assumption",
        measured=measured,
        notes="T015 batch pipeline; cite beside fee×slip",
    )


def _signals(strategy_id: str, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    from quantflow.strategy.catalog import get_strategy_definition

    definition = get_strategy_definition(strategy_id)
    strategy = definition.factory()
    return strategy.generate_signals(df)


def _fee_slip_grid(df: pd.DataFrame, strategy_id: str) -> list[dict[str, Any]]:
    entries, exits = _signals(strategy_id, df)
    close = df["close"]
    engine = BacktestEngine()
    rows: list[dict[str, Any]] = []
    for fee, slip in FEE_CELLS:
        # BacktestEngine uses a single fee param; model slip as extra fee for grid.
        result = engine.run_backtest(
            close=close,
            entries=entries,
            exits=exits,
            initial_capital=100_000.0,
            fee=float(fee) + float(slip),
            strategy_id=strategy_id,
            symbol=SYMBOL,
        )
        rows.append(
            {
                "taker_fee": fee,
                "slippage": slip,
                "sharpe": result.sharpe_ratio,
                "return_pct": result.total_return * 100.0
                if abs(result.total_return) <= 5
                else result.total_return,
                "max_drawdown": result.max_drawdown,
                "num_trades": result.num_trades,
                "note": "slip added into fee for vectorized engine approximation",
            }
        )
    return rows


def evaluate_candidate(
    strategy_id: str,
    df: pd.DataFrame,
    *,
    funding_tca: dict[str, Any],
    full_gate: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Evaluate one strategy; return pass/rejected row (fail-closed)."""
    row: dict[str, Any] = {
        "strategy": strategy_id,
        "status": "rejected",
        "reasons": [],
        "decision": "NO-GO",
    }
    if dry_run:
        # Structural dry-run: no backtest; still require funding block present.
        try:
            assert_promotion_cost_ready(
                {
                    "decision": "GO",
                    "fee_slip_grid": [
                        {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 0.0, "return_pct": 0.0},
                        {
                            "taker_fee": 0.001,
                            "slippage": 0.001,
                            "sharpe": 0.0,
                            "return_pct": 0.0,
                        },
                    ],
                    "funding_tca": funding_tca,
                }
            )
            row["status"] = "pass"
            row["decision"] = "DRY-PASS"
            row["note"] = "dry-run: cost/funding schema only; no alpha claim"
        except CostFidelityError as exc:
            row["reasons"].append(str(exc))
        return row

    try:
        grid = _fee_slip_grid(df, strategy_id)
    except Exception as exc:  # noqa: BLE001 — isolate candidates
        row["reasons"].append(f"signal/backtest failed: {exc}")
        return row

    report: dict[str, Any] = {
        "decision": "GO",  # provisional; cost gate may reject
        "strategy": strategy_id,
        "fee_slip_grid": grid,
        "funding_tca": funding_tca,
    }
    report = attach_cost_fidelity(
        report, fee_slip_grid=grid, funding_tca=funding_tca
    )

    if full_gate:
        try:
            from quantflow.strategy.validation.gate import validation_gate

            entries, exits = _signals(strategy_id, df)
            gate = validation_gate(
                df["close"],
                entries,
                exits,
                fee=0.001,
                initial_capital=100_000.0,
            )
            report["checks"] = {
                **(report.get("checks") or {}),
                **(gate.get("checks") or {}),
            }
            report["decision"] = gate.get("decision", "NO-GO")
            report["gate_reason"] = gate.get("reason")
            if report["decision"] != "GO":
                row["reasons"].append(f"validation_gate: {gate.get('reason', 'NO-GO')}")
        except Exception as exc:  # noqa: BLE001
            row["reasons"].append(f"full_gate failed: {exc}")
            report["decision"] = "NO-GO"

    try:
        # Cost/funding fail-closed regardless of provisional decision.
        assert_promotion_cost_ready(
            {**report, "decision": "GO"},  # force cost checks to run
        )
    except CostFidelityError as exc:
        row["reasons"].append(str(exc))
        row["status"] = "rejected"
        row["decision"] = "NO-GO"
        row["report"] = {
            "fee_slip_grid": grid,
            "funding_tca": {
                k: funding_tca.get(k)
                for k in (
                    "mode",
                    "source",
                    "estimated_annual_drag_pct",
                    "effective_abs_funding_per_event",
                )
            },
        }
        return row

    if report.get("decision") == "GO" and not row["reasons"]:
        row["status"] = "pass"
        row["decision"] = "GO" if full_gate else "COST-PASS"
    else:
        row["status"] = "rejected"
        row["decision"] = report.get("decision", "NO-GO")

    # Compact report (no huge series)
    row["report"] = {
        "fee_slip_grid": grid,
        "funding_tca": {
            k: funding_tca.get(k)
            for k in (
                "mode",
                "source",
                "estimated_annual_drag_pct",
                "effective_abs_funding_per_event",
            )
        },
        "gate_decision": report.get("decision"),
    }
    return row


def run_batch(
    strategies: list[str],
    *,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    full_gate: bool = False,
    dry_run: bool = False,
    require_pin: bool = True,
) -> dict[str, Any]:
    warn_if_unpinned(start, end, require_pin=require_pin, context="batch_gate_pipeline")
    try:
        start_ms, end_ms = parse_window_ms(start, end)
    except ContractPinError as exc:
        raise SystemExit(f"pin error: {exc}") from exc

    funding = _funding_block()
    if dry_run:
        df = pd.DataFrame()
        pin_meta = {
            "start": start,
            "end": end,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "data_fingerprint": {"aggregate": "dry-run"},
        }
    else:
        df = _load_bars(start_ms, end_ms)
        pin = build_window_pin(
            start=start, end=end, frames={SYMBOL: df}, timeframe="1h"
        )
        pin_meta = pin.to_dict()

    candidates: list[dict[str, Any]] = []
    for sid in strategies:
        print(f"[batch-gate] evaluate {sid} ...", flush=True)
        candidates.append(
            evaluate_candidate(
                sid, df, funding_tca=funding, full_gate=full_gate, dry_run=dry_run
            )
        )

    n_pass = sum(1 for c in candidates if c["status"] == "pass")
    n_rej = sum(1 for c in candidates if c["status"] == "rejected")
    overall = "pass" if n_rej == 0 and n_pass == len(candidates) else "fail_closed"
    if not candidates:
        overall = "fail_closed"

    return {
        "kind": "batch_gate_pipeline",
        "task": "T015",
        "ran_at": datetime.now(UTC).isoformat(),
        "mode": "dry-run" if dry_run else ("full-gate" if full_gate else "fast-cost"),
        "symbol": SYMBOL,
        "window": pin_meta,
        "funding_tca_summary": {
            "mode": funding.get("mode"),
            "source": funding.get("source"),
            "estimated_annual_drag_pct": funding.get("estimated_annual_drag_pct"),
        },
        "strategies": strategies,
        "candidates": candidates,
        "summary": {
            "n": len(candidates),
            "pass": n_pass,
            "rejected": n_rej,
            "overall": overall,
            "rule": "any missing fee×slip or funding_tca → rejected (fail-closed)",
        },
        "day_session_hook": (
            "After paper_day_session preflight: "
            "python scripts/batch_gate_pipeline.py --strategies trend_following"
        ),
    }


def _write_md(payload: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Batch gate pipeline ({payload.get('mode')})",
        "",
        f"- ran_at: `{payload.get('ran_at')}`",
        f"- overall: **{payload.get('summary', {}).get('overall')}**",
        f"- pass/rejected: {payload.get('summary', {}).get('pass')}/"
        f"{payload.get('summary', {}).get('rejected')}",
        f"- funding: mode={payload.get('funding_tca_summary', {}).get('mode')} "
        f"drag≈{payload.get('funding_tca_summary', {}).get('estimated_annual_drag_pct')}%",
        "",
        "| strategy | status | decision | reasons |",
        "|----------|--------|----------|---------|",
    ]
    for c in payload.get("candidates") or []:
        reasons = "; ".join(c.get("reasons") or []) or "—"
        lines.append(
            f"| {c.get('strategy')} | {c.get('status')} | {c.get('decision')} | {reasons} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated strategy ids",
    )
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--full-gate", action="store_true", help="Run validation_gate (slow)")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Schema-only pass for cost/funding without backtests",
    )
    ap.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 even if some candidates rejected",
    )
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument(
        "--after-day-session",
        action="store_true",
        help="Hint mode: same as default fast; documents day-session hook",
    )
    args = ap.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    if not strategies:
        print("[batch-gate] no strategies", file=sys.stderr)
        return 2

    payload = run_batch(
        strategies,
        start=args.start,
        end=args.end,
        full_gate=args.full_gate,
        dry_run=args.dry_run,
    )
    if args.after_day_session:
        payload["hook"] = "after-day-session"

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md = out.with_suffix(".md")
    _write_md(payload, md)
    print(f"[batch-gate] overall={payload['summary']['overall']} → {out}")
    print(f"[batch-gate] summary md → {md}")
    for c in payload["candidates"]:
        print(f"  {c['strategy']}: {c['status']} ({c['decision']})")

    if payload["summary"]["overall"] != "pass" and not args.allow_partial:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
