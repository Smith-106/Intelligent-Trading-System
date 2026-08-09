#!/usr/bin/env python3
"""Multi-symbol portfolio replay — equal / risk_parity / shared_cap.

Modes:
  - equal: shared book, classic tf + nested on BTC+ETH(+SOL), equal strategy alloc
  - shared_cap: same shared book with tighter position_limit_pct / max_positions
  - shared_risk_parity: shared book + periodic symbol-level RP rebalance
  - risk_parity: silo capital split by inverse price-vol weights, sum equity

Baseline: BTC-only single-symbol for the same window.

    python scripts/multi_symbol_replay.py
    python scripts/multi_symbol_replay.py --symbols BTC/USDT,ETH/USDT --from 2021-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
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
    build_multi_symbol_session,
    build_session,
    replay,
    replay_multi,
)

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _load_1h(store: Any, symbol: str, start_ms: int | None, end_ms: int) -> pd.DataFrame:
    df = store.query(symbol, start=start_ms, end=end_ms, timeframe="1h")
    if df.empty:
        return df
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _intersect_frames(
    frames: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Inner-join on timestamp so every symbol has the same calendar."""
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


def _inv_vol_weights(frames: dict[str, pd.DataFrame], window: int = 720) -> dict[str, float]:
    """Inverse realized-vol weights from close returns (no look-ahead on full sample:
    uses the first ``window`` bars only for weight estimation — warm-up prefix).
    """
    vols: dict[str, float] = {}
    for sym, df in frames.items():
        close = df["close"].astype(float)
        rets = close.pct_change().dropna()
        sample = rets.iloc[: max(window, 30)]
        if len(sample) < 30:
            vols[sym] = 1.0
            continue
        sigma = float(sample.std())
        vols[sym] = sigma if sigma > 1e-12 else 1.0
    inv = {s: 1.0 / v for s, v in vols.items()}
    total = sum(inv.values())
    return {s: w / total for s, w in inv.items()}


async def _run_shared(
    frames: dict[str, pd.DataFrame],
    *,
    capital: float,
    max_position_pct: float,
    max_positions: int,
    gate: str,
    fee: float,
    slip: float,
) -> dict[str, float]:
    cfg = AppConfig(
        execution=ExecutionConfig(taker_fee=fee, maker_fee=fee * 0.8, slippage=slip),
        risk=RiskConfig(position_limit_pct=max_position_pct, max_positions=max_positions),
    )
    sink = RecordingSink()
    symbols = sorted(frames.keys())
    session = build_multi_symbol_session(
        "trend_following",
        symbols,
        capital=capital,
        sink=sink,
        config=cfg,
        max_position_pct=max_position_pct,
        max_positions=max_positions,
    )
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay_multi(session, frames, fills, risk, direction_gate=gate, entry_tf="1h")
    rep = aggregate(curve, fills, risk, sink.alerts, capital, entry_tf="1h")
    return _float_rep(rep)


async def _run_shared_risk_parity(
    frames: dict[str, pd.DataFrame],
    *,
    capital: float,
    max_position_pct: float,
    max_positions: int,
    gate: str,
    fee: float,
    slip: float,
    rebalance_every_n_bars: int = 48,
    min_samples: int = 30,
) -> dict[str, float]:
    """Shared-book multi-symbol with periodic symbol-level risk-parity rebalance."""
    from quantflow.common.config import PortfolioOptimizationConfig

    cfg = AppConfig(
        execution=ExecutionConfig(taker_fee=fee, maker_fee=fee * 0.8, slippage=slip),
        risk=RiskConfig(
            position_limit_pct=max_position_pct,
            max_positions=max_positions,
            portfolio_optimization=PortfolioOptimizationConfig(
                enabled=True,
                method="risk_parity",
                level="symbol",
                rebalance_every_n_bars=rebalance_every_n_bars,
                min_samples=min_samples,
                vol_window=min_samples,
            ),
        ),
    )
    sink = RecordingSink()
    session = build_multi_symbol_session(
        "trend_following",
        list(frames.keys()),
        capital,
        sink,
        config=cfg,
        research_risk_bypass=True,
        max_position_pct=max_position_pct,
        max_positions=max_positions,
    )
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay_multi(session, frames, fills, risk, direction_gate=gate, entry_tf="1h")
    rep = aggregate(curve, fills, risk, sink.alerts, capital, entry_tf="1h")
    out = _float_rep(rep)
    # Last rebalanced symbol weights for diagnostics (may be empty if never fired).
    out["symbol_weights"] = dict(session._portfolio.symbol_allocation)  # type: ignore[assignment]
    return out


async def _run_silo_risk_parity(
    frames: dict[str, pd.DataFrame],
    *,
    capital: float,
    gate: str,
    fee: float,
    slip: float,
) -> dict[str, float]:
    weights = _inv_vol_weights(frames)
    # Sum equity curves of independent single-symbol sessions with capital*weight.
    combined: dict[int, float] = {}
    total_orders = 0.0
    total_fills = 0.0
    for sym, df in frames.items():
        w = weights[sym]
        cap = capital * w
        if cap < 100:
            continue
        cfg = AppConfig(
            execution=ExecutionConfig(taker_fee=fee, maker_fee=fee * 0.8, slippage=slip)
        )
        sink = RecordingSink()
        session = build_session("trend_following", cap, sink, config=cfg, research_risk_bypass=True)
        fills: list[dict[str, object]] = []
        risk: list[dict[str, object]] = []
        curve = await replay(session, df, sym, fills, risk, direction_gate=gate, entry_tf="1h")
        total_orders += float(len({f.get("order_id") for f in fills}))
        total_fills += float(len(fills))
        for pt in curve:
            ts = int(pt["timestamp"])
            combined[ts] = combined.get(ts, 0.0) + float(pt["equity"])

    if not combined:
        return {
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_annualized": float("nan"),
            "orders": 0.0,
            "weights": weights,  # type: ignore[dict-item]
        }
    curve_list = [{"timestamp": float(ts), "equity": eq} for ts, eq in sorted(combined.items())]
    # Manual aggregate-ish metrics
    final = curve_list[-1]["equity"]
    ret = (final / capital - 1.0) * 100.0 if capital else 0.0
    peak = 0.0
    max_dd = 0.0
    for p in curve_list:
        eq = p["equity"]
        if eq > peak:
            peak = eq
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    equity = [p["equity"] for p in curve_list]
    rets = pd.Series(equity).pct_change().dropna()
    if len(rets) > 2 and rets.std() != 0:
        sharpe = float(rets.mean() / rets.std() * math.sqrt(24 * 365))
    else:
        sharpe = float("nan")
    return {
        "return_pct": round(ret, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "sharpe_annualized": round(sharpe, 4) if sharpe == sharpe else float("nan"),
        "orders": total_orders,
        "fills": total_fills,
        "weights": weights,  # type: ignore[dict-item]
    }


def _float_rep(rep: dict[str, object]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


async def _run_single(
    df: pd.DataFrame,
    symbol: str,
    *,
    capital: float,
    gate: str,
    fee: float,
    slip: float,
) -> dict[str, float]:
    cfg = AppConfig(execution=ExecutionConfig(taker_fee=fee, maker_fee=fee * 0.8, slippage=slip))
    sink = RecordingSink()
    session = build_session("trend_following", capital, sink, config=cfg, research_risk_bypass=True)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, df, symbol, fills, risk, direction_gate=gate, entry_tf="1h")
    return _float_rep(aggregate(curve, fills, risk, sink.alerts, capital, entry_tf="1h"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--start", default="2021-01-01", help="common start (SOL constraint)")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--gate", default="nested")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slip", type=float, default=0.001)
    ap.add_argument("--out", default="data/paper_replay/multi_symbol_replay.json")
    ap.add_argument(
        "--require-pin",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail if start/end missing (default true; T011)",
    )
    args = ap.parse_args()

    from quantflow.data.store import DataStore

    from quantflow.strategy.research.contract_pin import (
        ContractPinError,
        build_window_pin,
        fingerprint_universe,
        parse_window_ms,
        warn_if_unpinned,
    )

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    try:
        warn_if_unpinned(
            args.start,
            args.end,
            require_pin=getattr(args, "require_pin", True),
            context="multi_symbol_replay",
        )
        start_ms, end_ms = parse_window_ms(args.start, args.end)
    except ContractPinError as exc:
        raise SystemExit(f"pin error: {exc}") from exc

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    raw: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _load_1h(store, sym, start_ms, end_ms)
        print(f"[msym] load {sym}: {len(df)} bars")
        if len(df) < 500:
            print(f"[msym] skip {sym}: insufficient")
            continue
        raw[sym] = df
    store.close()

    frames = _intersect_frames(raw)
    if len(frames) < 2:
        raise SystemExit(f"need ≥2 symbols after intersect; got {list(frames)}")
    n = len(next(iter(frames.values())))
    print(f"[msym] intersect symbols={list(frames)} bars={n}")

    pin = build_window_pin(
        start=args.start,
        end=args.end,
        frames=frames,
        timeframe="1h",
        require_pin=getattr(args, "require_pin", True),
    )
    # Re-fingerprint post-intersect frames (actual research calendar).
    data_fp = fingerprint_universe(frames)

    results: dict[str, Any] = {
        "window": {
            "start": args.start,
            "end": args.end,
            "start_ms": pin.start_ms,
            "end_ms": pin.end_ms,
            "bars": n,
            "timeframe": "1h",
        },
        "data_fingerprint": data_fp,
        "require_pin": getattr(args, "require_pin", True),
    }
    print(f"[msym] data_fingerprint.aggregate={data_fp.get('aggregate')}")

    # BTC baseline on same window if present
    if "BTC/USDT" in frames:
        print("\n=== BTC-only baseline ===")
        btc = asyncio.run(
            _run_single(
                frames["BTC/USDT"],
                "BTC/USDT",
                capital=args.capital,
                gate=args.gate,
                fee=args.fee,
                slip=args.slip,
            )
        )
        results["btc_only"] = btc
        print(
            f"  ret={btc.get('return_pct'):+.2f}% sh={btc.get('sharpe_annualized')} "
            f"dd={btc.get('max_drawdown_pct')} orders={btc.get('orders')}"
        )

    # equal (shared book, default 20% pos limit, max_positions=len)
    print("\n=== equal (shared book) ===")
    equal = asyncio.run(
        _run_shared(
            frames,
            capital=args.capital,
            max_position_pct=0.20,
            max_positions=max(5, len(frames)),
            gate=args.gate,
            fee=args.fee,
            slip=args.slip,
        )
    )
    results["equal"] = equal
    print(
        f"  ret={equal.get('return_pct'):+.2f}% sh={equal.get('sharpe_annualized')} "
        f"dd={equal.get('max_drawdown_pct')} orders={equal.get('orders')}"
    )

    # shared_cap: tighter single-name + max positions = n
    print("\n=== shared_cap (pos 10%, max_positions=n) ===")
    shared = asyncio.run(
        _run_shared(
            frames,
            capital=args.capital,
            max_position_pct=0.10,
            max_positions=len(frames),
            gate=args.gate,
            fee=args.fee,
            slip=args.slip,
        )
    )
    results["shared_cap"] = shared
    print(
        f"  ret={shared.get('return_pct'):+.2f}% sh={shared.get('sharpe_annualized')} "
        f"dd={shared.get('max_drawdown_pct')} orders={shared.get('orders')}"
    )

    # shared-book symbol-level risk parity (periodic rebalance)
    print("\n=== shared_risk_parity (shared book + symbol RP rebalance) ===")
    srp = asyncio.run(
        _run_shared_risk_parity(
            frames,
            capital=args.capital,
            max_position_pct=0.20,
            max_positions=max(5, len(frames)),
            gate=args.gate,
            fee=args.fee,
            slip=args.slip,
        )
    )
    results["shared_risk_parity"] = {k: v for k, v in srp.items() if k != "symbol_weights"}
    results["shared_risk_parity_weights"] = srp.get("symbol_weights")
    print(
        f"  ret={srp.get('return_pct'):+.2f}% sh={srp.get('sharpe_annualized')} "
        f"dd={srp.get('max_drawdown_pct')} orders={srp.get('orders')} "
        f"w={srp.get('symbol_weights')}"
    )

    # risk_parity silo
    print("\n=== risk_parity (silo inv-vol weights) ===")
    rp = asyncio.run(
        _run_silo_risk_parity(
            frames,
            capital=args.capital,
            gate=args.gate,
            fee=args.fee,
            slip=args.slip,
        )
    )
    results["risk_parity"] = {k: v for k, v in rp.items() if k != "weights"}
    results["risk_parity_weights"] = rp.get("weights")
    print(
        f"  ret={rp.get('return_pct'):+.2f}% sh={rp.get('sharpe_annualized')} "
        f"dd={rp.get('max_drawdown_pct')} orders={rp.get('orders')} "
        f"weights={rp.get('weights')}"
    )

    # ranking by sharpe then return
    modes = ["btc_only", "equal", "shared_cap", "risk_parity"]
    scored = []
    for m in modes:
        if m not in results:
            continue
        r = results[m]
        sh = r.get("sharpe_annualized")
        sh_v = sh if isinstance(sh, (int, float)) and sh == sh else -99.0
        scored.append((m, sh_v, r.get("return_pct") or -99.0))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    results["winner_by_sharpe"] = scored[0][0] if scored else None
    results["symbols"] = list(frames.keys())
    results["gate"] = args.gate
    results["fee"] = args.fee
    results["slip"] = args.slip

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[msym] written {out}")
    print(f"{'mode':>12} {'ret%':>8} {'sharpe':>8} {'maxDD':>8} {'orders':>8}")
    for m, _, _ in scored:
        r = results[m]
        print(
            f"{m:>12} {r.get('return_pct', float('nan')):>+8.2f} "
            f"{(r.get('sharpe_annualized') if r.get('sharpe_annualized') == r.get('sharpe_annualized') else float('nan')):>8.3f} "
            f"{r.get('max_drawdown_pct', float('nan')):>8.2f} "
            f"{r.get('orders', 0):>8.0f}"
        )
    print(f"[msym] winner={results['winner_by_sharpe']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
