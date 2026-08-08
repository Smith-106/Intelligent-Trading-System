#!/usr/bin/env python3
"""Reframe experiments: fee/slippage sensitivity + risk fidelity on classic 1h.

Baseline strategy: trend_following classic + nested direction gate.
Does NOT search signals — quantifies how execution/risk assumptions change
reported performance (problem redefinition).

    python scripts/reframe_sensitivity_1h.py
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig  # noqa: E402
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)


async def _eval(
    bars: pd.DataFrame,
    symbol: str,
    *,
    taker_fee: float,
    slippage: float,
    research_risk_bypass: bool,
    max_drawdown: float,
    kill_switch: bool,
    gate: str | bool = "nested",
) -> dict[str, float]:
    cfg = AppConfig(
        execution=ExecutionConfig(
            taker_fee=taker_fee, maker_fee=taker_fee * 0.8, slippage=slippage
        ),
        risk=RiskConfig(kill_switch_enabled=kill_switch, max_drawdown=max_drawdown),
    )
    sink = RecordingSink()
    session = build_session(
        "trend_following",
        100_000.0,
        sink,
        config=cfg,
        research_risk_bypass=research_risk_bypass,
    )
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars, symbol, fills, risk, direction_gate=gate, entry_tf="1h")
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0, entry_tf="1h")
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--days", type=int, default=0, help="0 = full available span to --end")
    ap.add_argument("--gate", default="nested")
    ap.add_argument("--out", default="data/paper_replay/reframe_sensitivity_1h.json")
    args = ap.parse_args()

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000)
    start_ms = None if args.days <= 0 else end_ms - args.days * 86_400_000
    df = store.query(args.symbol, start=start_ms, end=end_ms, timeframe="1h")
    store.close()
    if df.empty:
        raise SystemExit("no 1h bars")
    bars = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    print(f"[reframe] bars={len(bars)} gate={args.gate}")

    # --- A: fee x slippage grid (research risk bypass ON) ---
    fees = [0.0, 0.0005, 0.001, 0.0015, 0.002]
    slips = [0.0, 0.0005, 0.001, 0.002]
    fee_rows: list[dict[str, Any]] = []
    for fee, slip in itertools.product(fees, slips):
        rep = asyncio.run(
            _eval(
                bars,
                args.symbol,
                taker_fee=fee,
                slippage=slip,
                research_risk_bypass=True,
                max_drawdown=-0.90,
                kill_switch=False,
                gate=args.gate,
            )
        )
        row = {
            "taker_fee": fee,
            "slippage": slip,
            "return_pct": rep.get("return_pct"),
            "max_drawdown_pct": rep.get("max_drawdown_pct"),
            "sharpe": rep.get("sharpe_annualized"),
            "orders": rep.get("orders"),
        }
        fee_rows.append(row)
        print(
            f"  fee={fee:.4f} slip={slip:.4f} ret={row['return_pct']:+.2f}% "
            f"sh={row['sharpe']} dd={row['max_drawdown_pct']:.2f}% orders={row['orders']}"
        )

    # --- B: risk fidelity ablation at default fee/slip ---
    risk_cases: list[dict[str, Any]] = [
        {"name": "research_bypass", "bypass": True, "dd": -0.90, "ks": False},
        {"name": "prod_risk_dd10", "bypass": False, "dd": -0.10, "ks": True},
        {"name": "prod_risk_dd15", "bypass": False, "dd": -0.15, "ks": True},
        {"name": "prod_risk_dd20_no_ks", "bypass": False, "dd": -0.20, "ks": False},
    ]
    risk_rows: list[dict[str, Any]] = []
    for case in risk_cases:
        rep = asyncio.run(
            _eval(
                bars,
                args.symbol,
                taker_fee=0.001,
                slippage=0.001,
                research_risk_bypass=bool(case["bypass"]),
                max_drawdown=float(case["dd"]),
                kill_switch=bool(case["ks"]),
                gate=args.gate,
            )
        )
        row = {
            "case": case["name"],
            "research_risk_bypass": case["bypass"],
            "max_drawdown": case["dd"],
            "kill_switch": case["ks"],
            "return_pct": rep.get("return_pct"),
            "max_drawdown_pct": rep.get("max_drawdown_pct"),
            "sharpe": rep.get("sharpe_annualized"),
            "orders": rep.get("orders"),
        }
        risk_rows.append(row)
        print(
            f"  risk[{case['name']}] ret={row['return_pct']:+.2f}% "
            f"sh={row['sharpe']} dd={row['max_drawdown_pct']:.2f}% orders={row['orders']}"
        )

    base = next(r for r in fee_rows if r["taker_fee"] == 0.001 and r["slippage"] == 0.001)
    zero = next(r for r in fee_rows if r["taker_fee"] == 0.0 and r["slippage"] == 0.0)

    payload = {
        "symbol": args.symbol,
        "entry_tf": "1h",
        "gate": args.gate,
        "strategy": "trend_following classic",
        "bars": len(bars),
        "fee_slip_grid": fee_rows,
        "risk_ablation": risk_rows,
        "summary": {
            "baseline_fee_slip_return_pct": base["return_pct"],
            "zero_cost_return_pct": zero["return_pct"],
            "cost_drag_pct_points": (zero["return_pct"] or 0) - (base["return_pct"] or 0),
            "note": "Positive cost_drag means zero-cost looks better than realistic fees",
            "multi_symbol_data": {
                "BTC_1h": "full",
                "ETH_1h": "only ~300 bars locally — insufficient for multi-year combo",
                "SOL_1h": "only ~300 bars locally — insufficient for multi-year combo",
            },
            "priority": [
                "1. Research-prod execution fidelity (fee/slip always wired)",
                "2. Research-prod risk fidelity (optional bypass; report both)",
                "3. Expand multi-symbol history before portfolio claims",
                "4. Signal search is lower ROI than the above",
            ],
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[reframe] written {out}")
    print(
        f"[reframe] zero-cost ret={zero['return_pct']:+.2f}% vs baseline "
        f"{base['return_pct']:+.2f}% drag={payload['summary']['cost_drag_pct_points']:+.2f}pp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
