"""Strategy scaffolding — generate StrategyBase skeleton + YAML + checklist.

P1 T005: one-command new strategy assets without hand-copying templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_HINT = Path(__file__).resolve().parents[1]  # quantflow/

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class ScaffoldError(ValueError):
    """Invalid scaffold request."""


@dataclass(frozen=True)
class ScaffoldResult:
    strategy_id: str
    class_name: str
    module_path: Path
    yaml_path: Path
    checklist_path: Path
    files_written: tuple[Path, ...]


def _to_class_name(strategy_id: str) -> str:
    return "".join(part.capitalize() for part in strategy_id.split("_")) + "Strategy"


def validate_strategy_id(strategy_id: str) -> str:
    sid = strategy_id.strip()
    if not _NAME_RE.match(sid):
        raise ScaffoldError(
            f"invalid strategy id {strategy_id!r}: use snake_case "
            r"[a-z][a-z0-9_]{1,48}"
        )
    return sid


def scaffold_strategy(
    strategy_id: str,
    *,
    repo_root: str | Path | None = None,
    force: bool = False,
    description: str = "",
) -> ScaffoldResult:
    """Write module + YAML + acceptance checklist for a new strategy.

    Does **not** auto-register into the catalog (fail-closed: explicit wiring
    required). Checklist lists registration steps.
    """
    sid = validate_strategy_id(strategy_id)
    root = Path(repo_root) if repo_root else Path.cwd()
    class_name = _to_class_name(sid)
    module_path = root / "quantflow" / "strategy" / "templates" / f"{sid}.py"
    yaml_path = root / "quantflow" / "config" / "strategies" / f"{sid}.yaml"
    checklist_path = root / "docs" / "research" / f"strategy-checklist-{sid}.md"

    for path in (module_path, yaml_path, checklist_path):
        if path.exists() and not force:
            raise ScaffoldError(f"refusing to overwrite existing file: {path}")

    module_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    checklist_path.parent.mkdir(parents=True, exist_ok=True)

    desc = description or f"{sid} strategy (scaffolded)"
    module_path.write_text(_module_source(sid, class_name, desc), encoding="utf-8")
    yaml_path.write_text(_yaml_source(sid, desc), encoding="utf-8")
    checklist_path.write_text(_checklist_source(sid, class_name), encoding="utf-8")

    return ScaffoldResult(
        strategy_id=sid,
        class_name=class_name,
        module_path=module_path,
        yaml_path=yaml_path,
        checklist_path=checklist_path,
        files_written=(module_path, yaml_path, checklist_path),
    )


def _module_source(strategy_id: str, class_name: str, description: str) -> str:
    return f'''"""{description}

Scaffolded by ``quantflow new-strategy``. Implement generate_signals + on_bar,
then register in catalog / CLI factories before use.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext


class {class_name}(StrategyBase):
    """{description}"""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="{strategy_id}", params=params)
        p = self._params
        self._fast = int(p.get("fast_ma_period", 10))
        self._slow = int(p.get("slow_ma_period", 30))
        self._bars: list[Bar] = []
        self._closes: list[float] = []

    def on_init(self, ctx: StrategyContext) -> None:
        self._bars.clear()
        self._closes.clear()

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        self._closes.append(float(bar.close))
        if len(self._closes) < self._slow + 1:
            return
        # Placeholder: replace with real logic; default is flat.
        _ = Direction.FLAT

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized path for research / validation_gate.

        Returns (entries, exits) boolean Series aligned to ``df`` index.
        """
        close = df["close"].astype(float)
        fast = close.rolling(self._fast, min_periods=self._fast).mean()
        slow = close.rolling(self._slow, min_periods=self._slow).mean()
        long_sig = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        exit_sig = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        entries = long_sig.fillna(False).astype(bool)
        exits = exit_sig.fillna(False).astype(bool)
        return entries, exits
'''


def _yaml_source(strategy_id: str, description: str) -> str:
    return f"""metadata:
  title: "{strategy_id}"
  description: "{description}"

param_space:
  fast_ma_period: [5, 20]
  slow_ma_period: [20, 60]

strategy:
  name: "{strategy_id}"
  symbol: "BTC/USDT"
  timeframe: "1h"
  params:
    fast_ma_period: 10
    slow_ma_period: 30
"""


def _checklist_source(strategy_id: str, class_name: str) -> str:
    return f"""# Strategy acceptance checklist — `{strategy_id}`

Generated by `quantflow new-strategy {strategy_id}`.

## Implement

- [ ] Fill `{class_name}.on_bar` / `generate_signals` with real logic
- [ ] Params documented in `quantflow/config/strategies/{strategy_id}.yaml`
- [ ] No future data in signals (PIT / lookahead scan if needed)

## Register (fail-closed — scaffold does **not** auto-wire)

- [ ] Add factory in `quantflow/strategy/catalog.py`
- [ ] Wire CLI `_get_strategy_factories()` if needed
- [ ] Unit test under `tests/unit/test_strategy_{strategy_id}.py`

## Validate before paper

- [ ] `quantflow research --strategy {strategy_id} ...`
- [ ] `quantflow validate --strategy {strategy_id} --method gate`
- [ ] Fee×slip grid attached for any GO narrative (P0 cost_fidelity)
- [ ] **Path A vs B**: daily `quantflow run` (path A, no nested gate) ≠ `run_baseline0.py` (path B, nested). Do not compare path A PnL to `gate.json`.

## Paper day-session

- [ ] `python scripts/preflight_baseline0_paper.py` (or day-session)
- [ ] Paper only — no `--mode live` for acceptance
"""
