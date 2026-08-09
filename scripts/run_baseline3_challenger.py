#!/usr/bin/env python3
"""Baseline-3 funding_rate challenger (T026).

Contract: docs/research/Candidate-Baseline-3.md

  - Control: classic trend_following
  - Challenger: funding_rate (+ OI confirmation)
  - BTC 1h nested, fee 0.1%/0.1%, fee×slip grid, funding_tca
  - No Optuna; Wave-C upgrade vs classic

Meta data is joined from DataStore meta_funding_rate / meta_open_interest.
If coverage is too thin for the full pin window, the runner **narrows the
effective window to the meta ∩ OHLCV intersection** and records BLOCKED/partial
flags — it does **not** invent funding series.

    python scripts/run_baseline3_challenger.py
    python scripts/run_baseline3_challenger.py --skip-fee-grid
    python scripts/run_baseline3_challenger.py --meta-root data/s3_verify/raw
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

import pandas as pd  # noqa: E402

from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig  # noqa: E402
from quantflow.strategy.research.contract_pin import (  # noqa: E402
    ContractPinError,
    build_window_pin,
    parse_window_ms,
    warn_if_unpinned,
)
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)
from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    build_funding_tca,
    summarize_measured_funding,
)

OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline3"
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
SYMBOL = "BTC/USDT"
GATE = "nested"
TRAIN_MONTHS = 24
FWD_MONTHS = 6
# Min meta points / bars for a non-blocked experiment
MIN_FUNDING_POINTS = 24
MIN_BARS_EFFECTIVE = 500

VARIANTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("classic", "trend_following", None),
    (
        "funding_rate",
        "funding_rate",
        {
            "entry_threshold": 0.001,
            "exit_threshold": 0.0003,
            "oi_lookback": 3,
            "oi_change_threshold": 0.05,
        },
    ),
]

FEE_GRID = [
    (0.0, 0.0),
    (0.001, 0.001),
    (0.002, 0.002),
]


def _sharpe(rep: dict[str, Any]) -> float:
    s = rep.get("sharpe_annualized", float("nan"))
    try:
        v = float(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")
    return v if v == v else float("nan")


def _pos_rate(rets: list[float]) -> float | None:
    if not rets:
        return None
    return sum(1 for r in rets if r >= 0) / len(rets)


def _load_adjudicate():
    import importlib.util

    path = REPO_ROOT / "scripts" / "run_baseline1_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline1_challenger", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.adjudicate


def _load_meta(
    meta_roots: list[Path],
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Load funding + OI from first meta root that has data."""
    from quantflow.data.store import DataStore

    notes: list[str] = []
    funding = pd.DataFrame()
    oi = pd.DataFrame()
    for root in meta_roots:
        if not root.is_dir():
            notes.append(f"meta root missing: {root}")
            continue
        store = DataStore(str(root), ":memory:")
        try:
            f = store.query_funding_rates(symbol, start=start_ms, end=end_ms)
            o = store.query_open_interest(symbol, start=start_ms, end=end_ms)
        finally:
            store.close()
        if f is not None and not f.empty:
            funding = f
            notes.append(f"funding from {root.as_posix()} n={len(f)}")
        if o is not None and not o.empty:
            oi = o
            notes.append(f"oi from {root.as_posix()} n={len(o)}")
        if not funding.empty:
            break
    return funding, oi, notes


def align_meta_to_bars(
    bars: pd.DataFrame,
    funding: pd.DataFrame,
    oi: pd.DataFrame,
) -> pd.DataFrame:
    """Forward-fill funding/OI onto 1h bar timestamps (asof backward)."""
    out = bars.copy()
    ts = out["timestamp"].astype("int64")

    if funding is None or funding.empty:
        out["funding_rate"] = 0.0
    else:
        f = funding.sort_values("timestamp")[["timestamp", "funding_rate"]].copy()
        f["timestamp"] = f["timestamp"].astype("int64")
        merged = pd.merge_asof(
            pd.DataFrame({"timestamp": ts}).sort_values("timestamp"),
            f,
            on="timestamp",
            direction="backward",
        )
        out["funding_rate"] = merged["funding_rate"].to_numpy()
        # leading NaN before first funding event
        out["funding_rate"] = out["funding_rate"].ffill().fillna(0.0)

    if oi is None or oi.empty:
        # Constant OI → pct_change ~0 → OI confirmation rarely fires.
        # Use a mild synthetic walk only when OI missing would zero all entries:
        # contract prefers real OI; if missing, mark and use ffill 1.0 baseline.
        out["open_interest"] = 1.0
    else:
        o = oi.sort_values("timestamp")[["timestamp", "open_interest"]].copy()
        o["timestamp"] = o["timestamp"].astype("int64")
        merged = pd.merge_asof(
            pd.DataFrame({"timestamp": ts}).sort_values("timestamp"),
            o,
            on="timestamp",
            direction="backward",
        )
        out["open_interest"] = merged["open_interest"].to_numpy()
        out["open_interest"] = out["open_interest"].ffill().bfill().fillna(1.0)

    return out


def make_funding_hook(df: pd.DataFrame):
    """Return bar_hook that feeds FundingRateStrategy before on_bar."""
    # Precompute arrays by position for itertuples order
    rates = df["funding_rate"].astype(float).to_numpy()
    ois = df["open_interest"].astype(float).to_numpy()
    state = {"i": 0}

    def hook(session: Any, row: Any) -> None:
        i = state["i"]
        state["i"] = i + 1
        if i >= len(rates):
            return
        for strat in session._strategies:
            inner = getattr(strat, "_inner", strat)
            if hasattr(inner, "update_funding_rate"):
                inner.update_funding_rate(float(rates[i]))
            if hasattr(inner, "update_open_interest"):
                inner.update_open_interest(float(ois[i]))
            if hasattr(inner, "set_freshness_gate"):
                # Meta present on this bar path → open entries
                inner.set_freshness_gate(True)

    return hook


async def _eval(
    strategy: str,
    params: dict[str, Any] | None,
    bars: pd.DataFrame,
    *,
    taker_fee: float = 0.001,
    slippage: float = 0.001,
    gate: str | bool = GATE,
    feed_meta: bool = False,
) -> dict[str, float]:
    cfg = AppConfig(
        execution=ExecutionConfig(
            taker_fee=taker_fee,
            maker_fee=taker_fee * 0.8,
            slippage=slippage,
            mode="paper",
        ),
        risk=RiskConfig(),
    )
    sink = RecordingSink()
    session = build_session(
        strategy,
        100_000.0,
        sink,
        config=cfg,
        params=params,
        research_risk_bypass=True,
    )
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    hook = make_funding_hook(bars) if feed_meta and strategy == "funding_rate" else None
    # Drop meta cols for Bar construction — replay only needs OHLCV fields
    bar_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    if feed_meta and strategy == "funding_rate":
        # keep meta on bars for hook index alignment; replay uses named attrs
        bars_for_replay = bars
    else:
        bars_for_replay = bars[bar_cols] if set(bar_cols).issubset(bars.columns) else bars

    curve = await replay(
        session,
        bars_for_replay,
        SYMBOL,
        fills,
        risk,
        direction_gate=gate,
        entry_tf="1h",
        bar_hook=hook,
    )
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0, entry_tf="1h")
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


def _wfo_segments(df: pd.DataFrame, end_ms: int) -> list[tuple[int, int, int]]:
    month_ms = 30 * 86_400_000
    train_ms = TRAIN_MONTHS * month_ms
    fwd_ms = FWD_MONTHS * month_ms
    start_ms = int(df["timestamp"].iloc[0])
    segments: list[tuple[int, int, int]] = []
    tr_end = start_ms + train_ms
    while tr_end + fwd_ms <= end_ms + 1:
        segments.append((start_ms, tr_end, tr_end + fwd_ms))
        tr_end += fwd_ms
    return segments


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--gate", default=GATE)
    ap.add_argument(
        "--require-pin",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    ap.add_argument("--skip-fee-grid", action="store_true")
    ap.add_argument(
        "--meta-root",
        action="append",
        default=None,
        help="Parquet root containing meta_funding_rate/ (repeatable)",
    )
    ap.add_argument(
        "--out-dir",
        default=str(OUT_DIR.relative_to(REPO_ROOT)).replace("\\", "/"),
    )
    args = ap.parse_args()

    try:
        warn_if_unpinned(
            args.start, args.end, require_pin=args.require_pin, context="baseline3"
        )
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        print(f"[b3] pin error: {exc}", file=sys.stderr)
        return 2

    meta_roots = (
        [Path(p) if Path(p).is_absolute() else REPO_ROOT / p for p in args.meta_root]
        if args.meta_root
        else [
            REPO_ROOT / "data" / "s3_verify" / "raw",
            REPO_ROOT / "data" / "parquet",
        ]
    )

    from quantflow.data.store import DataStore

    ohlcv_store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        raw = ohlcv_store.query(SYMBOL, start=start_ms, end=end_ms, timeframe="1h")
    finally:
        ohlcv_store.close()
    if raw.empty:
        print("[b3] no OHLCV bars in pin window", file=sys.stderr)
        return 2

    funding, oi, meta_notes = _load_meta(meta_roots, SYMBOL, start_ms, end_ms)
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    data_status = "ok"
    block_reasons: list[str] = []
    if funding.empty or len(funding) < MIN_FUNDING_POINTS:
        data_status = "BLOCKED"
        block_reasons.append(
            f"funding points {len(funding)} < min {MIN_FUNDING_POINTS}"
        )

    # Narrow effective window to funding coverage ∩ OHLCV when partial
    eff_start, eff_end = start_ms, end_ms
    if not funding.empty:
        fmin = int(funding["timestamp"].min())
        fmax = int(funding["timestamp"].max())
        eff_start = max(start_ms, fmin)
        eff_end = min(end_ms, fmax)
        if eff_start > start_ms or eff_end < end_ms:
            if data_status != "BLOCKED":
                data_status = "NARROWED"
            meta_notes.append(
                f"effective window narrowed to funding span "
                f"{pd.to_datetime(eff_start, unit='ms')}→"
                f"{pd.to_datetime(eff_end, unit='ms')}"
            )

    df = raw[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(
        drop=True
    )
    df = df[(df["timestamp"] >= eff_start) & (df["timestamp"] <= eff_end)].reset_index(
        drop=True
    )
    if len(df) < MIN_BARS_EFFECTIVE and data_status != "BLOCKED":
        data_status = "BLOCKED"
        block_reasons.append(f"effective bars {len(df)} < {MIN_BARS_EFFECTIVE}")

    if data_status == "BLOCKED":
        blocked = {
            "status": "BLOCKED",
            "reasons": block_reasons,
            "meta_notes": meta_notes,
            "funding_points": int(len(funding)),
            "oi_points": int(len(oi)),
            "contract_window": {"start": args.start, "end": args.end},
            "task": "T026",
            "at": datetime.now(UTC).isoformat(),
        }
        (out_dir / "adjudication.json").write_text(
            json.dumps(
                {
                    "verdict": "BLOCKED",
                    "upgrade_to_baseline1": False,
                    "reason": "; ".join(block_reasons) or "meta data insufficient",
                    "data_status": blocked,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (out_dir / "run_meta.json").write_text(
            json.dumps(blocked, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[b3] BLOCKED: {block_reasons}", file=sys.stderr)
        # Still write empty shells for contract paths
        for name in ("funding_wfo.json", "fee_slip_grid.json", "funding_tca.json"):
            if not (out_dir / name).exists():
                (out_dir / name).write_text("{}", encoding="utf-8")
        return 3

    df = align_meta_to_bars(df, funding, oi)
    pin = build_window_pin(
        start=args.start,
        end=args.end,
        frames={SYMBOL: df[["timestamp", "open", "high", "low", "close", "volume"]]},
        timeframe="1h",
        require_pin=args.require_pin,
    )
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
    segments = _wfo_segments(df, int(df["timestamp"].iloc[-1]))
    # If window too short for 24m/6m, fall back to half-window OOS folds
    if len(segments) < 1:
        meta_notes.append(
            "WFO 24m/6m produced 0 segments — using 50/50 single OOS fold"
        )
        mid = int(df["timestamp"].iloc[len(df) // 2])
        segments = [
            (int(df["timestamp"].iloc[0]), mid, int(df["timestamp"].iloc[-1]) + 1)
        ]

    print(
        f"[b3] status={data_status} bars={len(df)} funding={len(funding)} "
        f"oi={len(oi)} segments={len(segments)} gate={args.gate}"
    )
    for n in meta_notes:
        print(f"  note: {n}")

    rows: list[dict[str, Any]] = []
    for label, strategy, params in VARIANTS:
        print(f"\n=== {label} ({strategy}) ===")
        feed = strategy == "funding_rate"
        full = asyncio.run(
            _eval(
                strategy,
                params,
                df.drop(columns="dt"),
                taker_fee=0.001,
                slippage=0.001,
                gate=args.gate,
                feed_meta=feed,
            )
        )
        print(
            f"  full@0.1%: ret={full.get('return_pct', float('nan')):+.2f}% "
            f"sh={full.get('sharpe_annualized', float('nan'))} "
            f"dd={full.get('max_drawdown_pct', float('nan'))} "
            f"orders={full.get('orders', 0)}"
        )

        oos_rets: list[float] = []
        oos_sharpes: list[float] = []
        oos_orders = 0.0
        for i, (_s, tr_end, fwd_end) in enumerate(segments):
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
            ].drop(columns="dt")
            if len(fwd) < 50:
                continue
            oos = asyncio.run(
                _eval(
                    strategy,
                    params,
                    fwd,
                    taker_fee=0.001,
                    slippage=0.001,
                    gate=args.gate,
                    feed_meta=feed,
                )
            )
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            sh = _sharpe(oos)
            oos_sharpes.append(sh if sh == sh else -10.0)
            oos_orders += float(oos.get("orders", 0.0))
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% "
                f"sh={oos_sharpes[-1]:.3f}"
            )

        rows.append(
            {
                "label": label,
                "strategy": strategy,
                "params": params,
                "full_return_pct": full.get("return_pct"),
                "full_max_dd_pct": full.get("max_drawdown_pct"),
                "full_sharpe": full.get("sharpe_annualized"),
                "full_orders": full.get("orders"),
                "wfo_segments": len(oos_rets),
                "wfo_oos_sum_pct": sum(oos_rets) if oos_rets else None,
                "wfo_oos_mean_pct": (sum(oos_rets) / len(oos_rets)) if oos_rets else None,
                "wfo_oos_mean_sharpe": (sum(oos_sharpes) / len(oos_sharpes))
                if oos_sharpes
                else None,
                "wfo_pos_rate": _pos_rate(oos_rets),
                "wfo_orders": oos_orders,
            }
        )

    fee_rows: list[dict[str, Any]] = []
    if not args.skip_fee_grid:
        print("\n=== fee×slip grid ===")
        bars = df.drop(columns="dt")
        for label, strategy, params in VARIANTS:
            feed = strategy == "funding_rate"
            for fee, slip in FEE_GRID:
                rep = asyncio.run(
                    _eval(
                        strategy,
                        params,
                        bars,
                        taker_fee=fee,
                        slippage=slip,
                        gate=args.gate,
                        feed_meta=feed,
                    )
                )
                cell = {
                    "label": label,
                    "strategy": strategy,
                    "taker_fee": fee,
                    "slippage": slip,
                    "return_pct": rep.get("return_pct"),
                    "sharpe": rep.get("sharpe_annualized"),
                    "max_drawdown_pct": rep.get("max_drawdown_pct"),
                    "orders": rep.get("orders"),
                }
                fee_rows.append(cell)
                print(
                    f"  {label} fee={fee} slip={slip} "
                    f"ret={cell['return_pct']} sh={cell['sharpe']}"
                )

    adjudicate = _load_adjudicate()
    adj = adjudicate(rows, fee_rows)
    # Tag baseline3
    adj["baseline"] = "B3"
    adj["data_status"] = data_status
    adj["meta_notes"] = meta_notes
    if data_status == "NARROWED":
        adj["reason"] = (
            (adj.get("reason") or "")
            + " | effective window narrowed to meta funding coverage"
        ).strip(" |")

    # funding_tca from measured series when available
    rates = [float(x) for x in funding["funding_rate"].tolist()] if not funding.empty else []
    measured = (
        summarize_measured_funding(
            rates,
            symbol=SYMBOL,
            start_ms=int(funding["timestamp"].min()) if not funding.empty else None,
            end_ms=int(funding["timestamp"].max()) if not funding.empty else None,
        )
        if rates
        else None
    )
    if measured:
        tca = build_funding_tca(mode="hybrid", measured=measured)
    else:
        tca = build_funding_tca(mode="assumption")

    run_meta = {
        "task": "T026",
        "contract": "Candidate-Baseline-3",
        "status": data_status,
        "symbol": SYMBOL,
        "gate": args.gate,
        "contract_window": {"start": args.start, "end": args.end},
        "effective_window_ms": {"start": eff_start, "end": eff_end},
        "bars": len(df),
        "funding_points": len(funding),
        "oi_points": len(oi),
        "wfo_segments": len(segments),
        "data_fingerprint": pin.data_fingerprint,
        "meta_notes": meta_notes,
        "ran_at": datetime.now(UTC).isoformat(),
    }

    (out_dir / "funding_wfo.json").write_text(
        json.dumps({"rows": rows, "segments": len(segments)}, indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / "fee_slip_grid.json").write_text(
        json.dumps({"rows": fee_rows}, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "funding_tca.json").write_text(
        json.dumps(tca, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "adjudication.json").write_text(
        json.dumps(adj, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2, default=str), encoding="utf-8"
    )

    print(f"\n[b3] verdict={adj.get('verdict')} upgrade={adj.get('upgrade_to_baseline1')}")
    print(f"[b3] wrote → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
