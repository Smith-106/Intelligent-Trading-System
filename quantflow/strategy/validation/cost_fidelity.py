"""Cost-fidelity gates for promotion and research reports.

P0 (strongest-gaps T001/T002): fee×slip grids and dual risk reporting are
mandatory inputs for GO narratives. Zero-cost Sharpe alone must not promote.

T014: funding / TCA assumptions must appear alongside fee×slip for GO
narratives (fail-closed when ``require_funding_tca`` is on — default for
``assert_promotion_cost_ready``).
"""

from __future__ import annotations

from typing import Any

# Default production cost pair (Baseline-0 contract).
DEFAULT_TAKER_FEE = 0.001
DEFAULT_SLIPPAGE = 0.001

# Minimal grid that must appear in a cost-fidelity attachment.
REQUIRED_FEE_POINTS = (0.0, 0.001)
REQUIRED_SLIP_POINTS = (0.0, 0.001)

# Crypto perpetual funding: 3 settlements / day is industry default (OKX/Binance).
DEFAULT_FUNDING_EVENTS_PER_DAY = 3.0
# Conservative long-bias assumption when measured series is short / missing.
# ~1 bp per 8h event ≈ 0.001 * 3 * 365 ≈ 1.1% / year if always paying.
DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT = 0.0001
VALID_FUNDING_MODES = frozenset({"assumption", "measured", "hybrid"})


class CostFidelityError(ValueError):
    """Raised when cost-fidelity requirements are missing or violated."""


def extract_cost_grid(report: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Return fee×slip rows from a validation / cost report if present."""
    if not isinstance(report, dict):
        return None
    for key in ("fee_slip_grid", "cost_grid", "fee_slip"):
        grid = report.get(key)
        if isinstance(grid, list) and grid:
            return grid
    cost = report.get("cost_fidelity")
    if isinstance(cost, dict):
        grid = cost.get("fee_slip_grid") or cost.get("cost_grid")
        if isinstance(grid, list) and grid:
            return grid
    checks = report.get("checks")
    if isinstance(checks, dict):
        cf = checks.get("cost_fidelity")
        if isinstance(cf, dict):
            grid = cf.get("fee_slip_grid") or cf.get("cost_grid")
            if isinstance(grid, list) and grid:
                return grid
    return None


def grid_has_fee_slip(
    grid: list[dict[str, Any]],
    *,
    fee: float,
    slip: float,
    tol: float = 1e-12,
) -> bool:
    for row in grid:
        if not isinstance(row, dict):
            continue
        rf = row.get("taker_fee", row.get("fee"))
        rs = row.get("slippage", row.get("slip"))
        try:
            if abs(float(rf) - fee) <= tol and abs(float(rs) - slip) <= tol:
                return True
        except (TypeError, ValueError):
            continue
    return False


def require_cost_grid(
    report: dict[str, Any] | None,
    *,
    require_zero_and_default: bool = True,
) -> list[dict[str, Any]]:
    """Fail-closed: promotion requires an explicit fee×slip grid.

    The grid must include at least the zero-cost cell and the default
    production cell (0.1% fee + 0.1% slip) when ``require_zero_and_default``.
    """
    grid = extract_cost_grid(report)
    if not grid:
        raise CostFidelityError(
            "cost fidelity missing: fee×slip grid required for paper promotion "
            "(attach fee_slip_grid or cost_fidelity.fee_slip_grid)"
        )
    if require_zero_and_default:
        if not grid_has_fee_slip(grid, fee=0.0, slip=0.0):
            raise CostFidelityError(
                "cost fidelity incomplete: grid must include zero-cost cell (fee=0, slip=0)"
            )
        if not grid_has_fee_slip(
            grid, fee=DEFAULT_TAKER_FEE, slip=DEFAULT_SLIPPAGE
        ):
            raise CostFidelityError(
                "cost fidelity incomplete: grid must include production cell "
                f"(fee={DEFAULT_TAKER_FEE}, slip={DEFAULT_SLIPPAGE})"
            )
    return grid


def _row_metric(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return None
    return None


def reject_zero_cost_only_go(report: dict[str, Any] | None) -> None:
    """Refuse GO narratives that only look good under zero cost.

    If zero-cost Sharpe (or return) is present and production-cost metric is
    missing or non-positive while zero-cost is positive, refuse.
    """
    grid = extract_cost_grid(report)
    if not grid:
        # require_cost_grid should have run first; keep defensive.
        raise CostFidelityError("cannot assess zero-cost-only GO without fee×slip grid")

    zero = next(
        (
            r
            for r in grid
            if isinstance(r, dict)
            and abs(float(r.get("taker_fee", r.get("fee", -1))) - 0.0) < 1e-12
            and abs(float(r.get("slippage", r.get("slip", -1))) - 0.0) < 1e-12
        ),
        None,
    )
    prod = next(
        (
            r
            for r in grid
            if isinstance(r, dict)
            and abs(float(r.get("taker_fee", r.get("fee", -1))) - DEFAULT_TAKER_FEE) < 1e-12
            and abs(float(r.get("slippage", r.get("slip", -1))) - DEFAULT_SLIPPAGE) < 1e-12
        ),
        None,
    )
    if zero is None or prod is None:
        raise CostFidelityError("grid missing zero or production cost cell")

    z_sh = _row_metric(zero, "sharpe", "sharpe_annualized")
    p_sh = _row_metric(prod, "sharpe", "sharpe_annualized")
    z_ret = _row_metric(zero, "return_pct", "return")
    p_ret = _row_metric(prod, "return_pct", "return")

    # Explicit flag from report authors.
    if isinstance(report, dict) and report.get("zero_cost_only_go") is True:
        raise CostFidelityError("zero_cost_only_go flag set — refuse promotion")

    # If production sharpe is non-positive / missing while zero-cost sharpe is
    # strongly positive, treat as zero-cost-only narrative.
    if z_sh is not None and z_sh > 0.5 and (p_sh is None or p_sh <= 0.0):
        raise CostFidelityError(
            f"zero-cost-only GO refused: zero sharpe={z_sh:.3f}, production sharpe={p_sh}"
        )
    if z_ret is not None and z_ret > 5.0 and (p_ret is None or p_ret <= 0.0):
        raise CostFidelityError(
            f"zero-cost-only GO refused: zero return={z_ret:.2f}%, production return={p_ret}"
        )


def require_dual_risk_report(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Require research_bypass vs production-risk dual rows when present as dual report."""
    if not isinstance(report, dict):
        raise CostFidelityError("dual risk report missing")
    rows = report.get("risk_ablation") or report.get("dual_risk") or report.get("risk_fidelity")
    if isinstance(report.get("cost_fidelity"), dict):
        rows = rows or report["cost_fidelity"].get("risk_ablation")
    if not isinstance(rows, list) or len(rows) < 2:
        raise CostFidelityError(
            "dual risk report missing: need risk_ablation with research_bypass and prod_risk"
        )
    names = {
        str(r.get("case", r.get("name", ""))).lower()
        for r in rows
        if isinstance(r, dict)
    }
    has_research = any("research" in n or "bypass" in n for n in names)
    has_prod = any("prod" in n or "production" in n for n in names)
    if not (has_research and has_prod):
        # Also accept explicit boolean pairs.
        bypass_vals = {
            r.get("research_risk_bypass")
            for r in rows
            if isinstance(r, dict) and "research_risk_bypass" in r
        }
        if True in bypass_vals and False in bypass_vals:
            return rows
        raise CostFidelityError(
            "dual risk report incomplete: need research_bypass and production-risk cases"
        )
    return rows


def extract_funding_tca(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull funding_tca / tca block from a validation or cost report."""
    if not isinstance(report, dict):
        return None
    for key in ("funding_tca", "tca", "funding_cost"):
        block = report.get(key)
        if isinstance(block, dict) and block:
            return block
    cost = report.get("cost_fidelity")
    if isinstance(cost, dict):
        block = cost.get("funding_tca") or cost.get("tca")
        if isinstance(block, dict) and block:
            return block
    checks = report.get("checks")
    if isinstance(checks, dict):
        cf = checks.get("cost_fidelity")
        if isinstance(cf, dict):
            block = cf.get("funding_tca") or cf.get("tca")
            if isinstance(block, dict) and block:
                return block
    return None


def build_funding_tca(
    *,
    mode: str = "assumption",
    assumed_abs_funding_per_event: float = DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT,
    events_per_day: float = DEFAULT_FUNDING_EVENTS_PER_DAY,
    measured: dict[str, Any] | None = None,
    taker_share: float = 1.0,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a funding / TCA block for cost reports (T014).

    ``mode``:
      - assumption: use assumed abs rate per funding event (no series required)
      - measured: require ``measured`` stats from a real series
      - hybrid: measured when present, else fall back to assumption

    Annualized drag estimate (rough, long-biased pay):
      abs_per_event * events_per_day * 365
    quoted as fraction (0.01 = 1%/year), not percentage points.
    """
    m = str(mode).lower().strip()
    if m not in VALID_FUNDING_MODES:
        raise CostFidelityError(
            f"funding_tca mode must be one of {sorted(VALID_FUNDING_MODES)}, got {mode!r}"
        )
    if not 0.0 <= float(taker_share) <= 1.0:
        raise CostFidelityError("taker_share must be in [0, 1]")

    measured_block = dict(measured) if isinstance(measured, dict) else None
    effective_abs = float(assumed_abs_funding_per_event)
    source = "assumption"

    if m in ("measured", "hybrid") and measured_block:
        for key in ("mean_abs_funding_per_event", "mean_abs_rate", "abs_mean"):
            if measured_block.get(key) is not None:
                try:
                    effective_abs = abs(float(measured_block[key]))
                    source = "measured"
                    break
                except (TypeError, ValueError):
                    continue
        if m == "measured" and source != "measured":
            raise CostFidelityError(
                "funding_tca mode=measured requires measured.mean_abs_funding_per_event"
            )
    elif m == "measured":
        raise CostFidelityError("funding_tca mode=measured requires measured stats dict")

    annual_drag = effective_abs * float(events_per_day) * 365.0
    # Scale by assumed taker share of notional that pays funding (spot≈0, perp long≈1).
    annual_drag_adj = annual_drag * float(taker_share)

    block: dict[str, Any] = {
        "mode": m,
        "source": source,
        "events_per_day": float(events_per_day),
        "assumed_abs_funding_per_event": float(assumed_abs_funding_per_event),
        "effective_abs_funding_per_event": effective_abs,
        "taker_share": float(taker_share),
        "estimated_annual_drag_fraction": annual_drag_adj,
        "estimated_annual_drag_pct": annual_drag_adj * 100.0,
        "display_alongside": ["fee_slip_grid"],
        "rule": (
            "GO narratives must cite funding_tca alongside fee×slip; "
            "missing funding_tca → NO-GO (T014 fail-closed)"
        ),
    }
    if measured_block is not None:
        block["measured"] = measured_block
    if notes:
        block["notes"] = notes
    return block


def require_funding_tca(report: dict[str, Any] | None) -> dict[str, Any]:
    """Fail-closed: GO path must include a funding_tca block (T014)."""
    block = extract_funding_tca(report)
    if not block:
        raise CostFidelityError(
            "funding_tca missing: GO narratives must include funding/TCA assumptions "
            "or measured series (attach funding_tca; T014)"
        )
    mode = str(block.get("mode", "")).lower()
    if mode and mode not in VALID_FUNDING_MODES:
        raise CostFidelityError(
            f"funding_tca.mode invalid: {block.get('mode')!r}; "
            f"expected one of {sorted(VALID_FUNDING_MODES)}"
        )
    # Require at least one quantitative drag or rate field.
    has_qty = any(
        block.get(k) is not None
        for k in (
            "estimated_annual_drag_fraction",
            "estimated_annual_drag_pct",
            "effective_abs_funding_per_event",
            "assumed_abs_funding_per_event",
        )
    )
    if not has_qty and not isinstance(block.get("measured"), dict):
        raise CostFidelityError(
            "funding_tca incomplete: need estimated drag or measured rates"
        )
    return block


def summarize_measured_funding(
    rates: list[float] | tuple[float, ...],
    *,
    symbol: str | None = None,
    n_events: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> dict[str, Any]:
    """Summarize a funding_rate series for ``build_funding_tca(measured=...)``."""
    if not rates:
        raise CostFidelityError("measured funding series is empty")
    vals = [float(x) for x in rates]
    abs_vals = [abs(v) for v in vals]
    n = len(vals)
    return {
        "symbol": symbol,
        "n_events": int(n_events if n_events is not None else n),
        "mean_rate": sum(vals) / n,
        "mean_abs_funding_per_event": sum(abs_vals) / n,
        "max_abs_rate": max(abs_vals),
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def attach_cost_fidelity(
    validation_report: dict[str, Any],
    *,
    fee_slip_grid: list[dict[str, Any]],
    risk_ablation: list[dict[str, Any]] | None = None,
    funding_tca: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a shallow-copied report with cost_fidelity attached under checks."""
    out = dict(validation_report)
    checks = dict(out.get("checks") or {})
    block: dict[str, Any] = {
        "fee_slip_grid": fee_slip_grid,
        "passed": True,
    }
    if risk_ablation is not None:
        block["risk_ablation"] = risk_ablation
    if funding_tca is not None:
        block["funding_tca"] = funding_tca
    checks["cost_fidelity"] = block
    out["checks"] = checks
    out["fee_slip_grid"] = fee_slip_grid
    if risk_ablation is not None:
        out["risk_ablation"] = risk_ablation
    if funding_tca is not None:
        out["funding_tca"] = funding_tca
    return out


def assert_promotion_cost_ready(
    validation_report: dict[str, Any] | None,
    *,
    require_funding: bool = True,
    require_execution_path: bool = True,
    require_fingerprint: bool = True,
) -> None:
    """Full cost-fidelity + path gate for paper registration (fail-closed).

    T014: ``require_funding`` defaults True — GO without funding_tca is refused.
    W14: ``require_execution_path`` defaults True — GO must cite paper_replay
    (or equivalent event path), not vectorized-only BacktestEngine/VectorBT.
    Pass ``require_funding=False`` / ``require_execution_path=False`` only for
    legacy research diagnostics.
    """
    require_cost_grid(validation_report)
    reject_zero_cost_only_go(validation_report)
    if require_funding:
        require_funding_tca(validation_report)
    if require_execution_path:
        from quantflow.strategy.validation.promotion_path import (
            PromotionPathError,
            assert_promotion_path_ready,
        )

        try:
            assert_promotion_path_ready(
                validation_report,
                require_fingerprint=require_fingerprint,
            )
        except PromotionPathError as exc:
            raise CostFidelityError(str(exc)) from exc
