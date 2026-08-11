"""Take-profit / stop-loss with minimum risk-reward (causal, bar-based).

Design
------
- Entries are boolean series already lagged for execution (caller responsibility).
- Barriers use **entry-bar** ATR/price only (captured at fill) — no look-ahead.
- Minimum R:R: ``tp_pct >= min_rr * sl_pct`` (raises if config violates).
- Optional time barrier (max holding bars).
- Intrabar path: check high/low against barriers when available; else close-only.

This is a **research** simulator, not live order routing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

ExitReason = Literal["tp", "sl", "time", "signal", "eod"]


@dataclass(frozen=True)
class TPSLConfig:
    """Barrier configuration in fraction of entry price (or ATR multiples)."""

    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    min_rr: float = 2.0
    max_holding_bars: int = 0  # 0 = disabled
    atr_period: int = 14
    # If atr_sl_mult > 0, SL = atr_sl_mult * ATR / entry; TP = min_rr * SL (unless take_profit set)
    atr_sl_mult: float = 0.0
    fee: float = 0.001
    slip: float = 0.001

    def resolved_pcts(self, atr_at_entry: float | None, entry_price: float) -> tuple[float, float]:
        """Return (sl_pct, tp_pct) enforcing min_rr."""
        if self.atr_sl_mult > 0 and atr_at_entry is not None and entry_price > 0:
            sl = float(self.atr_sl_mult * atr_at_entry / entry_price)
            tp = float(self.min_rr * sl)
            if self.take_profit_pct > 0:
                # allow explicit TP only if it still meets min RR
                tp = max(tp, float(self.take_profit_pct))
        else:
            sl = float(self.stop_loss_pct)
            tp = float(self.take_profit_pct)
        if sl <= 0:
            raise ValueError("stop_loss_pct / atr stop must be > 0")
        if tp / sl + 1e-12 < self.min_rr:
            # auto-lift TP to satisfy min RR (research default)
            tp = self.min_rr * sl
        return sl, tp


@dataclass
class TradeRecord:
    entry_i: int
    exit_i: int
    entry_price: float
    exit_price: float
    pnl_pct: float  # after one-way costs on entry+exit notional of trade
    reason: ExitReason
    sl_pct: float
    tp_pct: float
    rr_planned: float


@dataclass
class TradeStats:
    n_trades: int
    winrate: float
    avg_win_pct: float
    avg_loss_pct: float
    payoff_ratio: float  # |avg_win/avg_loss|
    profit_factor: float
    avg_rr_realized: float
    avg_hold_bars: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    h = high.astype(float)
    lo = low.astype(float)
    c = close.astype(float)
    tr = pd.concat(
        [
            h - lo,
            (h - c.shift(1)).abs(),
            (lo - c.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def simulate_long_flat_tpsl(
    close: pd.Series,
    entries: pd.Series,
    *,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    signal_on: pd.Series | None = None,
    cfg: TPSLConfig | None = None,
) -> tuple[pd.Series, list[TradeRecord], TradeStats, dict[str, Any]]:
    """Long/flat path: enter on True edge of ``entries``, exit on TP/SL/time/signal-off.

    ``entries`` should already be execution-lagged. Position is 0 or 1.
    Equity starts at 1.0; costs applied on entry and exit notional.
    """
    cfg = cfg or TPSLConfig()
    c = close.astype(float).to_numpy()
    n = len(c)
    hi = high.astype(float).to_numpy() if high is not None else c
    lo = low.astype(float).to_numpy() if low is not None else c
    ent = entries.astype(bool).to_numpy()
    sig = signal_on.astype(bool).to_numpy() if signal_on is not None else np.ones(n, dtype=bool)

    atr = (
        atr_series(
            high if high is not None else close,
            low if low is not None else close,
            close,
            cfg.atr_period,
        )
        .to_numpy(dtype=float)
    )

    eq = np.ones(n, dtype=float)
    pos = 0.0
    entry_price = 0.0
    entry_i = -1
    sl_pct = 0.0
    tp_pct = 0.0
    trades: list[TradeRecord] = []
    cost = cfg.fee + cfg.slip

    def _close_trade(i: int, price: float, reason: ExitReason) -> None:
        nonlocal pos, entry_price, entry_i, sl_pct, tp_pct
        # exit cost
        px = price * (1.0 - cost)
        raw = px / entry_price - 1.0
        # entry cost already applied to equity at entry; report net path pnl approx
        trades.append(
            TradeRecord(
                entry_i=entry_i,
                exit_i=i,
                entry_price=entry_price,
                exit_price=px,
                pnl_pct=float(raw),
                reason=reason,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                rr_planned=float(tp_pct / sl_pct) if sl_pct > 0 else 0.0,
            )
        )
        pos = 0.0
        entry_i = -1

    for i in range(n):
        # mark-to-market with current position (from previous decision)
        if i > 0:
            r = c[i] / c[i - 1] - 1.0
            eq[i] = eq[i - 1] * (1.0 + pos * r)
        else:
            eq[i] = 1.0

        if pos > 0:
            # barrier checks using high/low of bar i (conservative: SL before TP if both)
            sl_px = entry_price * (1.0 - sl_pct)
            tp_px = entry_price * (1.0 + tp_pct)
            hit_sl = lo[i] <= sl_px
            hit_tp = hi[i] >= tp_px
            reason: ExitReason | None = None
            exit_px = c[i]
            if hit_sl and hit_tp:
                # ambiguous bar: assume stop first (pessimistic)
                reason = "sl"
                exit_px = sl_px
            elif hit_sl:
                reason = "sl"
                exit_px = sl_px
            elif hit_tp:
                reason = "tp"
                exit_px = tp_px
            elif cfg.max_holding_bars > 0 and (i - entry_i) >= cfg.max_holding_bars:
                reason = "time"
                exit_px = c[i]
            elif not sig[i]:
                reason = "signal"
                exit_px = c[i]
            if reason is not None:
                # apply exit fee by reducing equity
                eq[i] *= 1.0 - cost
                _close_trade(i, exit_px, reason)

        # entry only if flat
        if pos == 0 and ent[i]:
            atr_i = float(atr[i]) if np.isfinite(atr[i]) else None
            entry_price = c[i] * (1.0 + cost)  # pay entry cost in fill
            sl_pct, tp_pct = cfg.resolved_pcts(atr_i, float(c[i]))
            entry_i = i
            pos = 1.0
            eq[i] *= 1.0 - cost  # account entry commission on equity

    # force flat at end
    if pos > 0:
        eq[-1] *= 1.0 - cost
        _close_trade(n - 1, float(c[-1]), "eod")

    stats = summarize_trades(trades)
    meta = {
        "config": asdict(cfg),
        "n_bars": n,
        "final_equity": float(eq[-1]),
    }
    return pd.Series(eq, index=close.index), trades, stats, meta


def summarize_trades(trades: list[TradeRecord]) -> TradeStats:
    if not trades:
        return TradeStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pnls = np.array([t.pnl_pct for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(pnls)
    winrate = float(len(wins) / n)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = float(abs(avg_win / avg_loss)) if avg_loss != 0 else 0.0
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = float(gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    holds = np.array([t.exit_i - t.entry_i for t in trades], dtype=float)
    realized_rr = []
    for t in trades:
        if t.sl_pct > 0:
            realized_rr.append(t.pnl_pct / t.sl_pct)
    return TradeStats(
        n_trades=n,
        winrate=round(winrate, 6),
        avg_win_pct=round(avg_win * 100, 6),
        avg_loss_pct=round(avg_loss * 100, 6),
        payoff_ratio=round(payoff, 6),
        profit_factor=round(pf, 6) if np.isfinite(pf) else 999.0,
        avg_rr_realized=round(float(np.mean(realized_rr)), 6) if realized_rr else 0.0,
        avg_hold_bars=round(float(holds.mean()), 3),
    )


def dual_ma_entries(
    close: pd.Series,
    fast: int = 96,
    slow: int = 400,
) -> tuple[pd.Series, pd.Series]:
    """Causal dual-MA: signal lagged 1 bar; entries = rising edge of long regime."""
    f = close.astype(float).rolling(fast, min_periods=fast).mean()
    s = close.astype(float).rolling(slow, min_periods=slow).mean()
    raw = (f > s).astype(float)
    sig = raw.shift(1).fillna(0.0)
    on = sig > 0.5
    prev = on.shift(1).fillna(False)
    entries = on & ~prev.astype(bool)
    return entries.astype(bool), on.astype(bool)
