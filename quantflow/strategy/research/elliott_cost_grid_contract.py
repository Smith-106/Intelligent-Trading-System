"""Elliott paper_replay package + fee×slip / funding_tca (W23b).

Extends W22 ``build_elliott_paper_replay_package`` with a minimal cost grid
suitable for ``require_cost_grid`` / ``require_funding_tca`` structure checks.

Still **not** auto-GO:

- ``promotion_eligible=false``
- grid rows use **replay equity delta as a single-cell proxy**, not a full
  multi-run optimizer — honest smoke for structure, not a sealed B0-class
  adjudication.

Usage::

    import asyncio
    from quantflow.strategy.research.elliott_cost_grid_contract import (
        build_elliott_cost_grid_package,
    )
    pkg = asyncio.run(build_elliott_cost_grid_package(n_bars=120))
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.strategy.research.elliott_paper_replay_contract import (
    ElliottPaperReplayPackage,
    build_elliott_paper_replay_package,
)
from quantflow.strategy.validation.cost_fidelity import (
    DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT,
    DEFAULT_FUNDING_EVENTS_PER_DAY,
    DEFAULT_SLIPPAGE,
    DEFAULT_TAKER_FEE,
    attach_cost_fidelity,
    build_funding_tca,
    require_cost_grid,
    require_funding_tca,
)
from quantflow.strategy.validation.promotion_path import check_promotion_path

# Minimal required points for cost fidelity (0/0 + production 0.1%/0.1%)
# plus an extra 0.2%/0.2% stress cell for fee-drag visibility.
_GRID_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (DEFAULT_TAKER_FEE, DEFAULT_SLIPPAGE),
    (0.002, 0.002),
)


@dataclass
class ElliottCostGridPackage:
    """W22 path package + cost_fidelity attachment."""

    base: ElliottPaperReplayPackage
    fee_slip_grid: list[dict[str, Any]] = field(default_factory=list)
    funding_tca: dict[str, Any] = field(default_factory=dict)
    cost_check: dict[str, Any] = field(default_factory=dict)
    path_check: dict[str, Any] = field(default_factory=dict)
    promotion_eligible: bool = False
    notes: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    output_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _proxy_grid_from_equity(
    initial: float,
    final: float,
    *,
    n_fills: int,
) -> list[dict[str, Any]]:
    """Build fee×slip rows with a crude cost-drag proxy from fill count.

    Not a re-simulation: each (fee, slip) cell subtracts an estimated round-trip
    cost proportional to fills. Sufficient for structure tests; not for GO.
    """
    base_ret = (final - initial) / initial if initial else 0.0
    # assume ~notional = initial each fill; round-trip fee+slip on that notion
    rows: list[dict[str, Any]] = []
    for fee, slip in _GRID_POINTS:
        drag = n_fills * (fee + slip)  # fractional of capital if full re-deploy
        adj = base_ret - drag
        rows.append(
            {
                "taker_fee": fee,
                "slippage": slip,
                "total_return_pct": adj * 100.0,
                "method": "proxy_from_fills",
                "n_fills": n_fills,
                "note": "W23b structure proxy — not multi-run reseat",
            }
        )
    return rows


async def _reseat_grid_from_replays(
    df: pd.DataFrame,
    *,
    symbol: str,
    capital: float,
    params: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """W24b: one paper_replay per fee×slip cell (true reseat, still not GO)."""
    from quantflow.common.config import AppConfig, ExecutionConfig, RiskConfig
    from quantflow.strategy.research.paper_replay import RecordingSink, build_session, replay

    rows: list[dict[str, Any]] = []
    for fee, slip in _GRID_POINTS:
        cfg = AppConfig(
            execution=ExecutionConfig(mode="paper", taker_fee=fee, slippage=slip),
            risk=RiskConfig(kill_switch_enabled=False, max_drawdown=-0.9),
        )
        sink = RecordingSink()
        session = build_session(
            "liu_yudong_wave",
            capital=capital,
            sink=sink,
            config=cfg,
            params=params,
            research_risk_bypass=True,
        )
        fills: list[dict[str, object]] = []
        risk_events: list[dict[str, object]] = []
        curve = await replay(session, df, symbol, fills=fills, risk_events=risk_events)
        final_eq = float(curve[-1]["equity"]) if curve else capital
        ret_pct = (final_eq - capital) / capital * 100.0 if capital else 0.0
        rows.append(
            {
                "taker_fee": fee,
                "slippage": slip,
                "total_return_pct": ret_pct,
                "final_equity": final_eq,
                "n_fills": len(fills),
                "method": "paper_replay_reseat",
                "note": "W24b multi-run reseat — still not sealed GO",
            }
        )
    return rows


async def build_elliott_cost_grid_package(
    *,
    df: pd.DataFrame | None = None,
    symbol: str = "BTC/USDT",
    n_bars: int = 200,
    capital: float = 100_000.0,
    params: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    contract_id: str = "elliott_paper_replay_cost_v1",
    reseat: bool = True,
) -> ElliottCostGridPackage:
    """Run W22 package then attach cost_fidelity + funding_tca (assumption).

    W24b: ``reseat=True`` (default) re-runs paper_replay once per fee×slip cell.
    Pass ``reseat=False`` for the faster W23b proxy_from_fills grid.
    """
    notes = [
        "W23b/W24b cost-grid package — structure for require_cost_grid/funding_tca",
        "promotion_eligible=false: grid is not sealed GO evidence",
        "Does not supersede B0; independent research contract",
    ]
    base = await build_elliott_paper_replay_package(
        df=df,
        symbol=symbol,
        n_bars=n_bars,
        capital=capital,
        params=params,
        output_dir=None,  # write combined package below
        contract_id=contract_id,
    )

    # Materialize frame for reseat (same path as smoke)
    from quantflow.strategy.research.elliott_wave_backtest import generate_synthetic_wave_data

    frame = generate_synthetic_wave_data(n_bars=n_bars) if df is None else df.copy()
    if "timestamp" not in frame.columns:
        frame["timestamp"] = list(range(len(frame)))

    cfg_params = dict(params or {})
    cfg_params.setdefault("allow_degraded_consensus", True)
    cfg_params.setdefault("require_confirmed_pivots", True)

    if reseat:
        grid = await _reseat_grid_from_replays(
            frame, symbol=symbol, capital=capital, params=cfg_params
        )
        notes.append("cost grid method=paper_replay_reseat (W24b)")
    else:
        grid = _proxy_grid_from_equity(
            capital,
            float(base.final_equity),
            n_fills=int(base.n_fills),
        )
        notes.append("cost grid method=proxy_from_fills (W23b)")

    funding = build_funding_tca(
        mode="assumption",
        assumed_abs_funding_per_event=DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT,
        events_per_day=DEFAULT_FUNDING_EVENTS_PER_DAY,
        notes="W23b/W24b assumption TCA for structure only",
    )

    report: dict[str, Any] = {
        "execution_path": "paper_replay",
        "data_fingerprint": base.data_fingerprint,
        "run_meta": {
            **base.run_meta,
            "cost_grid_method": "paper_replay_reseat" if reseat else "proxy_from_fills",
        },
        "decision": "NO_GO",  # explicit — never claim GO from package alone
        "promotion_eligible": False,
        "contract_id": contract_id,
    }
    report = attach_cost_fidelity(report, fee_slip_grid=grid, funding_tca=funding)

    path_check = check_promotion_path(report, require_fingerprint=True)
    cost_ok = True
    cost_reasons: list[str] = []
    try:
        require_cost_grid(report)
    except Exception as e:
        cost_ok = False
        cost_reasons.append(str(e))
    try:
        require_funding_tca(report)
    except Exception as e:
        cost_ok = False
        cost_reasons.append(str(e))
    cost_check = {"passed": cost_ok, "reasons": cost_reasons}

    out_path: str | None = None
    if output_dir is not None:
        dest = Path(output_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "run_meta.json").write_text(
            json.dumps(report["run_meta"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (dest / "cost_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary = {
            "contract_id": contract_id,
            "path_check_passed": path_check.get("passed"),
            "cost_check_passed": cost_ok,
            "promotion_eligible": False,
            "n_fills": base.n_fills,
            "decision": "NO_GO",
            "cost_grid_method": "paper_replay_reseat" if reseat else "proxy_from_fills",
        }
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        out_path = str(dest)
        notes.append(f"wrote cost package under {out_path}")

    return ElliottCostGridPackage(
        base=base,
        fee_slip_grid=grid,
        funding_tca=funding,
        cost_check=cost_check,
        path_check=path_check,
        promotion_eligible=False,
        notes=notes,
        report=report,
        output_dir=out_path,
    )
