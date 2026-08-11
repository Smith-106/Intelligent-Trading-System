"""Path B multi-window OOS with honest n_trials (research only).

GO discussion is allowed only after multi-window OOS evidence.
``promotion_eligible`` is always False — never auto-promote to live.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.research.benchmark_excess import (
    buy_hold_equity_from_close,
    excess_vs_benchmark,
    gate_beats_benchmark,
)
from quantflow.strategy.research.dual_path_profiles import path_b_profile
from quantflow.strategy.research.n_trials_budget import (
    TrialsBreakdown,
    account_n_trials,
    assert_honest_n_trials,
    grid_size,
)
from quantflow.strategy.research.tpsl import (
    TPSLConfig,
    dual_ma_entries,
    simulate_long_flat_tpsl,
)
from quantflow.strategy.research.tpsl_gate_adapter import barrier_param_space


@dataclass
class WindowOOSResult:
    window_id: int
    is_start: int
    is_end: int
    oos_start: int
    oos_end: int
    oos_bars: int
    excess_return_pct: float
    max_dd_pct: float
    winrate: float
    payoff_ratio: float
    n_trades: int
    gate_vs_btc: str
    best_params: dict[str, float]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slice_df(df: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    return df.iloc[start:end].reset_index(drop=True)


def _eval_path_b_slice(
    df: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    min_rr: float,
    max_holding_bars: int,
    fee: float,
    slip: float,
) -> dict[str, Any]:
    if df is None or df.empty or "close" not in df.columns:
        raise ValueError("slice requires close")
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    entries, sig_on = dual_ma_entries(close, fast=fast, slow=slow)
    cfg = TPSLConfig(
        stop_loss_pct=float(stop_loss_pct),
        take_profit_pct=float(take_profit_pct),
        min_rr=float(min_rr),
        max_holding_bars=int(max_holding_bars),
        fee=float(fee),
        slip=float(slip),
    )
    eq, _trades, stats, _meta = simulate_long_flat_tpsl(
        close, entries, high=high, low=low, signal_on=sig_on, cfg=cfg
    )
    btc_eq = buy_hold_equity_from_close(close)
    vs = excess_vs_benchmark(eq, btc_eq, label="PATH_B_OOS", benchmark_label="BTC_HODL")
    gate = gate_beats_benchmark(vs)
    return {
        "excess_return_pct": float(vs.excess_return_pct),
        "max_dd_pct": float(vs.strategy_max_dd_pct),
        "return_pct": float(vs.strategy_return_pct),
        "winrate": float(getattr(stats, "winrate", 0.0) or 0.0),
        "payoff_ratio": float(getattr(stats, "payoff_ratio", 0.0) or 0.0),
        "n_trades": int(getattr(stats, "n_trades", 0) or 0),
        "gate_vs_btc": str(gate.get("decision")),
        "beats_btc": bool(vs.beats_benchmark),
    }


def _is_select_params(
    df_is: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    space: dict[str, tuple[Any, ...]],
    fee: float,
    slip: float,
    max_candidates: int = 12,
) -> dict[str, float]:
    """Greedy IS selection on discrete barrier grid (honest search)."""
    sls = list(space.get("stop_loss_pct", (0.04,)))
    rrs = list(space.get("min_rr", (2.5,)))
    holds = list(space.get("max_holding_bars", (0,)))
    candidates: list[dict[str, float]] = []
    for sl in sls:
        for rr in rrs:
            for hold in holds:
                candidates.append(
                    {
                        "stop_loss_pct": float(sl),
                        "min_rr": float(rr),
                        "take_profit_pct": float(sl) * float(rr),
                        "max_holding_bars": float(hold),
                    }
                )
                if len(candidates) >= max_candidates:
                    break
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    best = candidates[0]
    best_score = -1e18
    for cand in candidates:
        try:
            m = _eval_path_b_slice(
                df_is,
                fast=fast,
                slow=slow,
                stop_loss_pct=cand["stop_loss_pct"],
                take_profit_pct=cand["take_profit_pct"],
                min_rr=cand["min_rr"],
                max_holding_bars=int(cand["max_holding_bars"]),
                fee=fee,
                slip=slip,
            )
        except Exception:
            continue
        # IS objective: excess - 0.25 * maxDD (research only)
        score = float(m["excess_return_pct"]) - 0.25 * float(m["max_dd_pct"])
        if score > best_score:
            best_score = score
            best = cand
    return best


def build_path_b_cost_attachment(
    *,
    fee: float,
    slip: float,
    funding_mode: str = "assumption",
) -> dict[str, Any]:
    """IMP-02: fee x slip grid + funding_tca structure (research attachment)."""
    from quantflow.strategy.validation.cost_fidelity import (
        DEFAULT_SLIPPAGE,
        DEFAULT_TAKER_FEE,
        build_funding_tca,
    )

    f = float(fee)
    s = float(slip)
    # Minimal honest grid: zero + profile + default production cell
    cells = {
        (0.0, 0.0),
        (f, s),
        (float(DEFAULT_TAKER_FEE), float(DEFAULT_SLIPPAGE)),
    }
    fee_slip_grid = [
        {
            "taker_fee": cf,
            "slippage": cs,
            "label": (
                "zero"
                if cf == 0.0 and cs == 0.0
                else ("profile" if cf == f and cs == s else "production_default")
            ),
        }
        for cf, cs in sorted(cells)
    ]
    funding_tca = build_funding_tca(
        mode=funding_mode,
        notes=(
            "IMP-02 Path B OOS research attachment; assumption mode when "
            "measured funding series not injected"
        ),
    )
    return {
        "fee_slip_grid": fee_slip_grid,
        "funding_tca": funding_tca,
        "profile_fee": f,
        "profile_slip": s,
        "note": "structure for cost narrative; not a paper_replay GO package",
    }


def run_path_b_multi_window_oos(
    df: pd.DataFrame,
    *,
    profile: dict[str, Any] | None = None,
    n_windows: int = 4,
    oos_ratio: float = 0.3,
    mode: str = "rolling",  # rolling | anchored
    param_space: dict[str, tuple[Any, ...]] | None = None,
    fixed_params: bool = False,
    claimed_n_trials: int | None = None,
    max_is_candidates: int = 12,
    data_fingerprint: dict[str, Any] | str | None = None,
    include_cost_attachment: bool = True,
    compare_modes: bool = False,
) -> dict[str, Any]:
    """Multi-window OOS for Path B TPSL with honest n_trials accounting.

    Returns a report where ``go_discussion_allowed`` is True only when:
    - honest n_trials (not underreported)
    - majority of OOS windows beat BTC (product axis)
    - median OOS excess > 0
    - median OOS maxDD is finite

    ``promotion_eligible`` is always False.

    IMP-01/02: attaches honest vectorized promotion_path + optional cost block.
    When ``compare_modes`` is True, also runs the alternate mode (rolling↔anchored)
    and stores summary under ``mode_compare`` (does not merge scores).
    """
    if df is None or df.empty or "close" not in df.columns:
        raise ValueError("df with close required (fail-closed)")
    if n_windows < 2:
        raise ValueError("n_windows must be >= 2 for multi-window OOS")
    if not (0.05 <= oos_ratio <= 0.5):
        raise ValueError("oos_ratio must be in [0.05, 0.5]")

    if compare_modes:
        primary = run_path_b_multi_window_oos(
            df,
            profile=profile,
            n_windows=n_windows,
            oos_ratio=oos_ratio,
            mode=mode,
            param_space=param_space,
            fixed_params=fixed_params,
            claimed_n_trials=claimed_n_trials,
            max_is_candidates=max_is_candidates,
            data_fingerprint=data_fingerprint,
            include_cost_attachment=include_cost_attachment,
            compare_modes=False,
        )
        alt_mode = "anchored" if mode == "rolling" else "rolling"
        alt = run_path_b_multi_window_oos(
            df,
            profile=profile,
            n_windows=n_windows,
            oos_ratio=oos_ratio,
            mode=alt_mode,
            param_space=param_space,
            fixed_params=fixed_params,
            claimed_n_trials=claimed_n_trials,
            max_is_candidates=max_is_candidates,
            data_fingerprint=data_fingerprint,
            include_cost_attachment=False,
            compare_modes=False,
        )
        primary["mode_compare"] = {
            "primary_mode": mode,
            "alternate_mode": alt_mode,
            "alternate_summary": alt.get("summary"),
            "alternate_research_go": alt.get("research_go"),
            "note": "dual-mode compare; not a combined_score",
        }
        return primary

    prof = profile or path_b_profile()
    fast = int(prof["fast"])
    slow = int(prof["slow"])
    fee = float(prof["fee"])
    slip = float(prof["slip"])
    space = param_space or barrier_param_space(
        stop_loss_pcts=(float(prof["stop_loss_pct"]), 0.03, 0.05),
        min_rrs=(float(prof["min_rr"]), 2.0, 3.0),
        max_holds=(int(prof.get("max_holding_bars") or 0),),
    )
    if fixed_params:
        space = {
            "stop_loss_pct": (float(prof["stop_loss_pct"]),),
            "min_rr": (float(prof["min_rr"]),),
            "max_holding_bars": (int(prof.get("max_holding_bars") or 0),),
        }

    n_bars = len(df)
    window_size = max(n_bars // n_windows, 1)
    oos_size = max(int(window_size * oos_ratio), 1)
    n_grid = grid_size(space)

    windows: list[WindowOOSResult] = []
    is_searches = 0

    for i in range(n_windows):
        is_start = 0 if mode == "anchored" else i * window_size
        is_end = (i + 1) * window_size - oos_size
        oos_start = is_end
        oos_end = (i + 1) * window_size
        if is_end <= is_start + 50 or oos_end <= oos_start + 20:
            continue
        is_end = min(is_end, n_bars)
        oos_end = min(oos_end, n_bars)
        if oos_start >= n_bars or is_end <= is_start:
            continue

        df_is = _slice_df(df, is_start, is_end)
        df_oos = _slice_df(df, oos_start, oos_end)
        notes: list[str] = []
        if fixed_params or n_grid <= 1:
            params = {
                "stop_loss_pct": float(prof["stop_loss_pct"]),
                "min_rr": float(prof["min_rr"]),
                "take_profit_pct": float(prof["take_profit_pct"]),
                "max_holding_bars": float(prof.get("max_holding_bars") or 0),
            }
            notes.append("fixed profile params on OOS")
        else:
            params = _is_select_params(
                df_is,
                fast=fast,
                slow=slow,
                space=space,
                fee=fee,
                slip=slip,
                max_candidates=max_is_candidates,
            )
            is_searches += min(n_grid, max_is_candidates)
            notes.append("IS discrete grid select → OOS apply")

        m = _eval_path_b_slice(
            df_oos,
            fast=fast,
            slow=slow,
            stop_loss_pct=float(params["stop_loss_pct"]),
            take_profit_pct=float(params["take_profit_pct"]),
            min_rr=float(params["min_rr"]),
            max_holding_bars=int(params["max_holding_bars"]),
            fee=fee,
            slip=slip,
        )
        windows.append(
            WindowOOSResult(
                window_id=i,
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
                oos_bars=len(df_oos),
                excess_return_pct=m["excess_return_pct"],
                max_dd_pct=m["max_dd_pct"],
                winrate=m["winrate"],
                payoff_ratio=m["payoff_ratio"],
                n_trades=m["n_trades"],
                gate_vs_btc=m["gate_vs_btc"],
                best_params={
                    "stop_loss_pct": float(params["stop_loss_pct"]),
                    "min_rr": float(params["min_rr"]),
                    "take_profit_pct": float(params["take_profit_pct"]),
                    "max_holding_bars": float(params["max_holding_bars"]),
                },
                notes=notes,
            )
        )

    if not windows:
        raise ValueError("no valid OOS windows produced (fail-closed)")

    # Honest n_trials: barrier grid × windows searched + window count itself
    breakdown = TrialsBreakdown(
        barrier_grid=int(n_grid if not fixed_params else 1),
        optimize_trials=int(is_searches),
        cpcv_paths=0,
        wfo_windows=len(windows),
        manual_sweeps=0,
        other=0,
    )
    acc = account_n_trials(breakdown)
    if claimed_n_trials is not None:
        acc = assert_honest_n_trials(claimed_n_trials, breakdown)

    excesses = np.array([w.excess_return_pct for w in windows], dtype=float)
    dds = np.array([w.max_dd_pct for w in windows], dtype=float)
    beat = sum(1 for w in windows if w.gate_vs_btc == "PASS")
    frac_beat = beat / len(windows)
    median_excess = float(np.median(excesses))
    median_dd = float(np.median(dds))
    # OOS consistency proxy: fraction of windows with positive excess
    frac_pos = float(np.mean(excesses > 0))

    go_discussion_allowed = (
        (not acc.underreported)
        and frac_beat >= 0.5
        and median_excess > 0.0
        and np.isfinite(median_dd)
        and len(windows) >= 2
    )
    # Research GO label — not live promotion
    research_go = "GO_DISCUSS" if go_discussion_allowed else "NO-GO"
    if acc.underreported:
        research_go = "NO-GO"
        go_discussion_allowed = False

    # IMP-01: honest research path + fingerprint (not paper_replay GO)
    fp = data_fingerprint
    if fp is None and "timestamp" in df.columns:
        try:
            from quantflow.strategy.research.contract_pin import fingerprint_ohlcv

            fp = {"aggregate": fingerprint_ohlcv(df), "source": "path_b_oos_slice"}
        except Exception:
            fp = {"aggregate": f"bars:{len(df)}", "source": "fallback_len"}

    cost_attachment = None
    if include_cost_attachment:
        cost_attachment = build_path_b_cost_attachment(fee=fee, slip=slip)

    out: dict[str, Any] = {
        "promotion_eligible": False,
        "hard_bind_entry": False,
        "research_go": research_go,
        "go_discussion_allowed": go_discussion_allowed,
        "n_trials_accounted": acc.n_trials_accounted,
        "n_trials_breakdown": acc.breakdown,
        "underreported": acc.underreported,
        "execution_path": "vectorized",
        "data_fingerprint": fp,
        "checks": {
            "promotion_path": {
                "execution_path": "vectorized",
                "data_fingerprint": fp,
                "promotion_eligible": False,
                "register_ready": False,
                "rule": (
                    "IMP-01: Path B OOS is research vectorized multi-window; "
                    "paper_replay required for any register/GO narrative"
                ),
            }
        },
        "notes": [
            *list(acc.notes),
            "GO_DISCUSS means research discussion only; never auto-promote",
            f"mode={mode} n_windows={n_windows} oos_ratio={oos_ratio}",
        ],
        "summary": {
            "n_windows_eval": len(windows),
            "frac_beat_btc": frac_beat,
            "frac_positive_excess": frac_pos,
            "median_oos_excess_pct": median_excess,
            "median_oos_max_dd_pct": median_dd,
            "mean_oos_excess_pct": float(np.mean(excesses)),
            "requested_n_windows": int(n_windows),
            "mode": mode,
        },
        "windows": [w.to_dict() for w in windows],
        "profile": {
            "fast": fast,
            "slow": slow,
            "stop_loss_pct": float(prof["stop_loss_pct"]),
            "take_profit_pct": float(prof["take_profit_pct"]),
            "min_rr": float(prof["min_rr"]),
            "fee": fee,
            "slip": slip,
        },
        "param_space": {k: list(v) for k, v in space.items()},
    }
    if cost_attachment is not None:
        out["cost_attachment"] = cost_attachment
        out["fee_slip_grid"] = cost_attachment["fee_slip_grid"]
        out["funding_tca"] = cost_attachment["funding_tca"]
    return out
