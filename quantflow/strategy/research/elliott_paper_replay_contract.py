"""Elliott Wave paper_replay **contract package** (W22b).

Builds a serializable research package with:

- ``execution_path=paper_replay``
- ``data_fingerprint`` (T011 ``fingerprint_ohlcv`` / universe block)
- optional disk write: ``run_meta.json`` + ``summary.json``

This satisfies W14 ``check_promotion_path`` structure. It does **not** auto
register, does **not** write GO, and does **not** replace cost-grid / streak
evidence. ``promotion_eligible`` stays False until a human adjudication.

Usage::

    import asyncio
    from quantflow.strategy.research.elliott_paper_replay_contract import (
        build_elliott_paper_replay_package,
    )
    pkg = asyncio.run(build_elliott_paper_replay_package(n_bars=200))
    assert pkg["run_meta"]["execution_path"] == "paper_replay"
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.strategy.research.contract_pin import fingerprint_ohlcv, fingerprint_universe
from quantflow.strategy.research.elliott_paper_replay_smoke import (
    run_elliott_paper_replay_smoke,
)
from quantflow.strategy.validation.promotion_path import check_promotion_path


@dataclass
class ElliottPaperReplayPackage:
    """Formal-ish package envelope (still research; not live promote)."""

    contract_id: str = "elliott_paper_replay_v1"
    is_smoke: bool = False
    promotion_eligible: bool = False
    execution_path: str = "paper_replay"
    strategy: str = "liu_yudong_wave"
    symbol: str = "BTC/USDT"
    n_bars: int = 0
    n_fills: int = 0
    final_equity: float = 0.0
    data_fingerprint: dict[str, Any] = field(default_factory=dict)
    run_meta: dict[str, Any] = field(default_factory=dict)
    path_check: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    output_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def build_elliott_paper_replay_package(
    *,
    df: pd.DataFrame | None = None,
    symbol: str = "BTC/USDT",
    n_bars: int = 200,
    capital: float = 100_000.0,
    params: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    contract_id: str = "elliott_paper_replay_v1",
) -> ElliottPaperReplayPackage:
    """Run paper_replay smoke path and stamp fingerprint + path check."""
    notes = [
        "W22b contract package — structure ready for W14 path check",
        "promotion_eligible=false: still need cost grid, streak, human GO",
        "Not a B0/B3 supersede; independent research contract id",
    ]

    # Materialize df for fingerprint before / after smoke
    from quantflow.strategy.research.elliott_wave_backtest import generate_synthetic_wave_data

    if df is None:
        frame = generate_synthetic_wave_data(n_bars=n_bars)
        notes.append("data_source=synthetic")
    else:
        frame = df.copy()
        notes.append("data_source=provided_df")
        n_bars = len(frame)

    if "timestamp" not in frame.columns:
        frame["timestamp"] = list(range(len(frame)))

    smoke = await run_elliott_paper_replay_smoke(
        df=frame,
        symbol=symbol,
        n_bars=n_bars,
        capital=capital,
        params=params,
    )

    fp_single = fingerprint_ohlcv(frame)
    fp_block = fingerprint_universe({symbol: frame})
    created = datetime.now(timezone.utc).isoformat()

    run_meta: dict[str, Any] = {
        "contract_id": contract_id,
        "execution_path": "paper_replay",
        "strategy": "liu_yudong_wave",
        "symbol": symbol,
        "n_bars": int(smoke.n_bars),
        "n_fills": int(smoke.n_fills),
        "n_risk_events": int(smoke.n_risk_events),
        "final_equity": float(smoke.final_equity),
        "initial_capital": float(capital),
        "data_fingerprint": fp_block,
        "ohlcv_fingerprint": fp_single,
        "is_smoke": False,
        "promotion_eligible": False,
        "created_at": created,
        "notes": notes,
    }

    # Report shape for promotion_path extractor
    report_for_check = {
        "execution_path": "paper_replay",
        "data_fingerprint": fp_block,
        "run_meta": run_meta,
    }
    path_check = check_promotion_path(report_for_check, require_fingerprint=True)

    out_path: str | None = None
    if output_dir is not None:
        dest = Path(output_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "run_meta.json").write_text(
            json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary = {
            "contract_id": contract_id,
            "path_check_passed": path_check.get("passed"),
            "n_fills": smoke.n_fills,
            "final_equity": smoke.final_equity,
            "data_fingerprint_aggregate": fp_block.get("aggregate"),
        }
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        out_path = str(dest)
        notes.append(f"wrote package under {out_path}")

    return ElliottPaperReplayPackage(
        contract_id=contract_id,
        is_smoke=False,
        promotion_eligible=False,
        execution_path="paper_replay",
        strategy="liu_yudong_wave",
        symbol=symbol,
        n_bars=int(smoke.n_bars),
        n_fills=int(smoke.n_fills),
        final_equity=float(smoke.final_equity),
        data_fingerprint=fp_block,
        run_meta=run_meta,
        path_check=path_check,
        notes=notes,
        output_dir=out_path,
    )
