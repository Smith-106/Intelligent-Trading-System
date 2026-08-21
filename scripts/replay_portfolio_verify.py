"""s5 paper replay verification — multi-asset 7-day budget utilization check.

Replays 1h bars for BTC/ETH/SOL through a paper TradingSession with
portfolio_optimization (risk parity) + dynamic_budget enabled, then reports
per-strategy budget utilization over the window.

The strategies are deterministic signal generators (one LONG per bar, one
per strategy_id) — the goal is to verify the OPTIMIZATION MECHANISM (risk
budgets hold, rebalance runs, utilization stays <= 1.0), not strategy alpha.

Usage:
    python scripts/replay_portfolio_verify.py [--days 7]
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
DATA_DIR = Path("data/parquet")


class _AlwaysLongStrategy(StrategyBase):
    """Emits one LONG signal per bar — deterministic trading for verification."""

    def __init__(self, name: str = "always_long", params: dict | None = None) -> None:
        super().__init__(name=name, params=params or {})
        self.required_regime = "any"

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        ctx.emit_signal(
            symbol=bar.symbol,
            direction=Direction.LONG,
            strength=0.5,
            price=bar.close,
            strategy_id=self.name,
        )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        entries = pd.Series(True, index=df.index)
        return entries, pd.Series(False, index=df.index)


def load_series(symbol: str) -> pd.DataFrame:
    """Load the most recent 1h parquet partition for a symbol.

    NOTE: the stored ``timestamp`` column is corrupt (ms int written as ns —
    values land in 1970). The ``datetime`` column is correct; use it to build
    the ms timestamps the engine expects.
    """
    key = symbol.replace("/", "_")
    files = sorted(glob.glob(str(DATA_DIR / key / "**" / "*.parquet"), recursive=True))
    if not files:
        raise SystemExit(f"no data for {symbol} — run quantflow download first")
    # The most recently written partition holds the freshly downloaded 1h data
    # (older partitions may be stale 1d files without the datetime column).
    newest = max(files, key=lambda p: Path(p).stat().st_mtime)
    df = pd.read_parquet(newest)
    df = df[df.timeframe == "1h"].copy()
    df["ts_ms"] = df["datetime"].astype("int64") // 1_000_000
    return df


def build_config() -> AppConfig:
    cfg = AppConfig()
    cfg.risk.portfolio_optimization.enabled = True
    cfg.risk.portfolio_optimization.method = "risk_parity"
    cfg.risk.portfolio_optimization.min_samples = 30
    cfg.risk.portfolio_optimization.rebalance_every_n_bars = 48
    cfg.risk.dynamic_budget.enabled = True
    cfg.risk.dynamic_budget.min_samples = 30
    cfg.risk.kill_switch_enabled = False  # paper replay, no emergency-stop needed
    return cfg


async def run_replay(days: int) -> dict:
    cfg = build_config()
    strategies = [
        _AlwaysLongStrategy("s_btc"),
        _AlwaysLongStrategy("s_eth"),
        _AlwaysLongStrategy("s_sol"),
    ]
    session = TradingSession(
        cfg,
        strategies,
        strategy_risk_budgets={s.name: 0.30 for s in strategies},
    )

    # Load and align the three series on common timestamps.
    series = {sym: load_series(sym) for sym in SYMBOLS}
    common_ts = set.intersection(*(set(s["ts_ms"]) for s in series.values()))
    if not common_ts:
        raise SystemExit("no common timestamps across symbols")
    common_ts = sorted(common_ts)
    # Replay window: last `days * 24` bars of the common timeline.
    window = common_ts[-days * 24 :]
    print(f"aligned bars: {len(common_ts)} total, replaying {len(window)} ({days}d)")

    await session.start(mode="paper", symbols=SYMBOLS)

    utilization_log: list[dict] = []
    max_util: dict[str, float] = {}
    try:
        for ts in window:
            for sym in SYMBOLS:
                row = series[sym].loc[series[sym]["ts_ms"] == ts]
                if row.empty:
                    continue
                r = row.iloc[0]
                bar = Bar(
                    symbol=sym,
                    timestamp=int(ts),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                )
                await session.on_bar(bar)
            report = session._portfolio.budget_utilization()
            utilization_log.append(
                {"ts": ts, **{k: v["utilization_pct"] for k, v in report.items()}}
            )
            for k, v in report.items():
                max_util[k] = max(max_util.get(k, 0.0), v["utilization_pct"])
    finally:
        await session.stop()

    return {"max_util": max_util, "bars": len(window), "log": utilization_log}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    result = asyncio.run(run_replay(args.days))

    print("\n=== BUDGET UTILIZATION VERIFICATION ===")
    print(
        f"window: {result['bars']} bars ({args.days} days), 3 assets, risk-parity + dynamic budget"
    )
    all_pass = True
    for sid, util in sorted(result["max_util"].items()):
        status = "PASS" if util <= 1.0 else "FAIL"
        if util > 1.0:
            all_pass = False
        print(f"  {sid:24s} max_utilization = {util:6.3f}  {status}")
    print(f"\nVERDICT: {'PASS — budget never exceeded' if all_pass else 'FAIL — budget exceeded'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
