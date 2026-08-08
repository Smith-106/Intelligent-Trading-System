#!/usr/bin/env python3
"""Walk-forward OOS check: shared-book equal vs symbol-level risk parity.

Unlike the full-window multi_symbol_replay, this script slides train/forward
windows and reports **out-of-sample only** metrics for:

  - equal: shared book, static equal strategy allocation
  - shared_risk_parity: shared book + periodic symbol-level RP rebalance

No Optuna — parameters are fixed (classic trend_following + nested gate).
This isolates the allocation method from signal-parameter overfit.

    python scripts/wfo_shared_rp.py
    python scripts/wfo_shared_rp.py --train-months 24 --fwd-months 6
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

import pandas as pd  # noqa: E402

from quantflow.common.config import (  # noqa: E402
    AppConfig,
    ExecutionConfig,
    PortfolioOptimizationConfig,
    RiskConfig,
)
from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_multi_symbol_session,
    replay_multi,
)

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _load_1h(store: Any, symbol: str, start_ms: int | None, end_ms: int) -> pd.DataFrame:
    df = store.query(symbol, start=start_ms, end=end_ms, timeframe="1h")
    if df.empty:
        return df
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _intersect_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if not frames:
        return {}
    common: set[int] | None = None
    for df in frames.values():
        ts = set(df["timestamp"].astype("int64").tolist())
        common = ts if common is None else (common & ts)
    if not common:
        return {k: df.iloc[0:0].copy() for k, df in frames.items()}
    out: dict[str, pd.DataFrame] = {}
    for sym, df in frames.items():
        out[sym] = (
            df[df["timestamp"].astype("int64").isin(common)]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
    return out


def _slice_frames(
    frames: dict[str, pd.DataFrame], start_ms: int, end_ms: int
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym, df in frames.items():
        mask = (df["timestamp"].astype("int64") >= start_ms) & (
            df["timestamp"].astype("int64") < end_ms
        )
        out[sym] = df.loc[mask].reset_index(drop=True)
    return out


def _float_rep(rep: dict[str, object]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


async def _run_mode(
    frames: dict[str, pd.DataFrame],
    *,
    mode: str,
    capital: float,
    gate: str,
    fee: float,
    slip: float,
    rebalance_every_n_bars: int,
    min_samples: int,
) -> dict[str, float]:
    symbols = sorted(frames.keys())
    n = len(next(iter(frames.values()))) if frames else 0
    if n < 200 or len(symbols) < 2:
        return {
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_annualized": float("nan"),
            "orders": 0.0,
            "bars": float(n),
        }

    if mode == "shared_risk_parity":
        risk = RiskConfig(
            position_limit_pct=0.20,
            max_positions=max(5, len(symbols)),
            portfolio_optimization=PortfolioOptimizationConfig(
                enabled=True,
                method="risk_parity",
                level="symbol",
                rebalance_every_n_bars=rebalance_every_n_bars,
                min_samples=min_samples,
                vol_window=min_samples,
            ),
        )
    else:
        risk = RiskConfig(
            position_limit_pct=0.20,
            max_positions=max(5, len(symbols)),
        )

    cfg = AppConfig(
        execution=ExecutionConfig(taker_fee=fee, maker_fee=fee * 0.8, slippage=slip),
        risk=risk,
    )
    sink = RecordingSink()
    session = build_multi_symbol_session(
        "trend_following",
        symbols,
        capital,
        sink,
        config=cfg,
        research_risk_bypass=True,
        max_position_pct=0.20,
        max_positions=max(5, len(symbols)),
    )
    fills: list[dict[str, object]] = []
    risk_ev: list[dict[str, object]] = []
    curve = await replay_multi(session, frames, fills, risk_ev, direction_gate=gate, entry_tf="1h")
    rep = aggregate(curve, fills, risk_ev, sink.alerts, capital, entry_tf="1h")
    out = _float_rep(rep)
    out["bars"] = float(n)
    if mode == "shared_risk_parity":
        out["symbol_weights"] = dict(session._portfolio.symbol_allocation)  # type: ignore[assignment]
    return out


def _windows(
    start: pd.Timestamp, end: pd.Timestamp, train_months: int, fwd_months: int
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Yield (train_start, train_end/fwd_start, fwd_end) triples."""
    out: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=train_months)
        fwd_end = train_end + pd.DateOffset(months=fwd_months)
        if fwd_end > end:
            break
        out.append((train_start, train_end, fwd_end))
        train_start = train_start + pd.DateOffset(months=fwd_months)
    return out


def _summarize(segments: list[dict[str, Any]], key: str) -> dict[str, float]:
    rets = [float(s[key]["return_pct"]) for s in segments if key in s]
    sharpes = [
        float(s[key]["sharpe_annualized"])
        for s in segments
        if key in s and s[key].get("sharpe_annualized") == s[key].get("sharpe_annualized")
    ]
    dds = [float(s[key]["max_drawdown_pct"]) for s in segments if key in s]
    pos = sum(1 for r in rets if r > 0)
    cum = 1.0
    for r in rets:
        cum *= 1.0 + r / 100.0
    return {
        "n_segments": float(len(rets)),
        "pos_segments": float(pos),
        "mean_return_pct": float(sum(rets) / len(rets)) if rets else 0.0,
        "mean_sharpe": float(sum(sharpes) / len(sharpes)) if sharpes else float("nan"),
        "mean_max_dd_pct": float(sum(dds) / len(dds)) if dds else 0.0,
        "cum_return_pct": float((cum - 1.0) * 100.0) if rets else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--fwd-months", type=int, default=6)
    ap.add_argument("--gate", default="nested")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slip", type=float, default=0.001)
    ap.add_argument("--rebalance-bars", type=int, default=48)
    ap.add_argument("--min-samples", type=int, default=30)
    ap.add_argument("--out", default="data/paper_replay/wfo_shared_rp.json")
    args = ap.parse_args()

    from quantflow.data.store import DataStore

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    end_ts = pd.Timestamp(args.end)
    start_ts = pd.Timestamp(args.start)
    end_ms = int(end_ts.timestamp() * 1000)
    start_ms = int(start_ts.timestamp() * 1000)

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    raw: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _load_1h(store, sym, start_ms, end_ms)
        print(f"[wfo-srp] load {sym}: {len(df)} bars")
        if len(df) < 500:
            continue
        raw[sym] = df
    store.close()

    frames = _intersect_frames(raw)
    if len(frames) < 2:
        raise SystemExit(f"need ≥2 symbols after intersect; got {list(frames)}")
    n = len(next(iter(frames.values())))
    print(f"[wfo-srp] intersect symbols={list(frames)} bars={n}")

    wins = _windows(start_ts, end_ts, args.train_months, args.fwd_months)
    print(f"[wfo-srp] windows={len(wins)} train={args.train_months}m fwd={args.fwd_months}m")

    segments: list[dict[str, Any]] = []
    for i, (_tr_s, tr_e, fw_e) in enumerate(wins):
        # OOS-only: replay each mode on the forward window (no train fit for RP —
        # symbol RP rebalances online inside the OOS window from its own history).
        oos_start = int(tr_e.timestamp() * 1000)
        oos_end = int(fw_e.timestamp() * 1000)
        oos = _slice_frames(frames, oos_start, oos_end)
        oos_n = len(next(iter(oos.values()))) if oos else 0
        print(
            f"\n=== window {i + 1}/{len(wins)} OOS {tr_e.date()} → {fw_e.date()} bars={oos_n} ==="
        )
        if oos_n < 200:
            print("  skip: insufficient OOS bars")
            continue

        seg: dict[str, Any] = {
            "oos_start": str(tr_e.date()),
            "oos_end": str(fw_e.date()),
            "oos_bars": oos_n,
        }
        for mode in ("equal", "shared_risk_parity"):
            rep = asyncio.run(
                _run_mode(
                    oos,
                    mode=mode,
                    capital=args.capital,
                    gate=args.gate,
                    fee=args.fee,
                    slip=args.slip,
                    rebalance_every_n_bars=args.rebalance_bars,
                    min_samples=args.min_samples,
                )
            )
            # Drop non-scalar for JSON cleanliness in summary tables
            clean = {k: v for k, v in rep.items() if isinstance(v, (int, float))}
            clean_weights = rep.get("symbol_weights")
            seg[mode] = clean
            if clean_weights is not None:
                seg[f"{mode}_weights"] = clean_weights
            print(
                f"  {mode:20s} ret={clean.get('return_pct', 0):+.2f}% "
                f"sh={clean.get('sharpe_annualized')} "
                f"dd={clean.get('max_drawdown_pct')} "
                f"orders={clean.get('orders')}"
            )
        segments.append(seg)

    summary = {
        "equal": _summarize(segments, "equal"),
        "shared_risk_parity": _summarize(segments, "shared_risk_parity"),
    }
    payload = {
        "window": {
            "start": args.start,
            "end": args.end,
            "train_months": args.train_months,
            "fwd_months": args.fwd_months,
            "symbols": list(frames.keys()),
            "bars": n,
        },
        "fee": args.fee,
        "slip": args.slip,
        "gate": args.gate,
        "segments": segments,
        "summary": summary,
    }

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[wfo-srp] written {out_path}")
    print(
        f"{'mode':20s} {'meanRet%':>10s} {'meanSh':>8s} {'meanDD%':>8s} "
        f"{'cumRet%':>10s} {'pos':>5s}"
    )
    for mode, s in summary.items():
        sh = s["mean_sharpe"]
        sh_s = f"{sh:.3f}" if sh == sh else "nan"
        print(
            f"{mode:20s} {s['mean_return_pct']:+10.2f} {sh_s:>8s} "
            f"{s['mean_max_dd_pct']:8.2f} {s['cum_return_pct']:+10.2f} "
            f"{int(s['pos_segments'])}/{int(s['n_segments'])}"
        )

    # Honest winner by mean OOS sharpe (NaN-safe)
    def _key(m: str) -> float:
        v = summary[m]["mean_sharpe"]
        return v if v == v else -99.0

    winner = max(summary, key=_key)
    print(f"[wfo-srp] winner_by_mean_oos_sharpe={winner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
