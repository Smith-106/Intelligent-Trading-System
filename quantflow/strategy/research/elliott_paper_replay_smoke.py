"""Elliott Wave **paper_replay** smoke (W21b) — event path, not vectorized GO.

Drives ``LiuYudongWaveStrategy`` through ``TradingSession.on_bar`` via the
existing paper_replay harness. Stamps ``execution_path=paper_replay`` for
research bookkeeping; **does not** auto-register or promote (still need
fills + streak + human GO).

Usage::

    import asyncio
    from quantflow.strategy.research.elliott_paper_replay_smoke import run_elliott_paper_replay_smoke
    report = asyncio.run(run_elliott_paper_replay_smoke(n_bars=200))
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from quantflow.strategy.research.elliott_wave_backtest import generate_synthetic_wave_data
from quantflow.strategy.research.paper_replay import RecordingSink, build_session, replay


@dataclass
class ElliottPaperReplaySmokeReport:
    is_smoke: bool = True
    promotion_eligible: bool = False
    execution_path: str = "paper_replay"
    strategy: str = "liu_yudong_wave"
    symbol: str = "BTC/USDT"
    n_bars: int = 0
    n_fills: int = 0
    n_risk_events: int = 0
    final_equity: float = 0.0
    initial_capital: float = 100_000.0
    notes: list[str] = field(default_factory=list)
    run_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_elliott_paper_replay_smoke(
    *,
    df: pd.DataFrame | None = None,
    symbol: str = "BTC/USDT",
    n_bars: int = 200,
    capital: float = 100_000.0,
    params: dict[str, Any] | None = None,
) -> ElliottPaperReplaySmokeReport:
    """Replay synthetic (or provided) OHLCV on paper event path for Elliott."""
    notes = [
        "W21b paper_replay smoke — execution_path=paper_replay but not auto-GO",
        "Requires separate promote evidence (streak/fills) before live",
    ]
    if df is None:
        df = generate_synthetic_wave_data(n_bars=n_bars)
        notes.append("data_source=synthetic")
    else:
        notes.append("data_source=provided_df")
        n_bars = len(df)

    # Ensure timestamp column for Bar construction
    if "timestamp" not in df.columns:
        df = df.copy()
        df["timestamp"] = list(range(len(df)))

    cfg_params = dict(params or {})
    cfg_params.setdefault("allow_degraded_consensus", True)
    cfg_params.setdefault("require_confirmed_pivots", True)
    cfg_params.setdefault("incremental_window", min(80, max(40, n_bars // 4)))

    sink = RecordingSink()
    session = build_session(
        "liu_yudong_wave",
        capital=capital,
        sink=sink,
        params=cfg_params,
        research_risk_bypass=True,
    )
    fills: list[dict[str, object]] = []
    risk_events: list[dict[str, object]] = []
    curve = await replay(session, df, symbol, fills=fills, risk_events=risk_events)
    final_eq = float(curve[-1]["equity"]) if curve else capital

    run_meta = {
        "execution_path": "paper_replay",
        "strategy": "liu_yudong_wave",
        "symbol": symbol,
        "n_bars": n_bars,
        "n_fills": len(fills),
        "is_smoke": True,
        "promotion_eligible": False,
    }
    return ElliottPaperReplaySmokeReport(
        symbol=symbol,
        n_bars=n_bars,
        n_fills=len(fills),
        n_risk_events=len(risk_events),
        final_equity=final_eq,
        initial_capital=capital,
        notes=notes,
        run_meta=run_meta,
    )
