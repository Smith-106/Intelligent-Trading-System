"""Coverage completion for validation/paper_readiness.py and cost_fidelity.py.

Pure-logic coverage for every documented branch:
- _parse_ts datetime/text/numeric flavors
- measure_* helpers, missing/invalid values
- check_paper_readiness config toggles
- cost grid extraction from all nesting locations
- grid_has_fee_slip numeric tolerance / bad rows
- require_cost_grid zero+production cells, relax flag
- reject_zero_cost_only_go status combinations
- require_dual_risk_report row-name / boolean-pair paths
- build_funding_tca assumption/measured/hybrid modes + validation
- require_funding_tca validation, attach/assert helpers
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantflow.strategy.validation.cost_fidelity import (
    CostFidelityError,
    DEFAULT_SLIPPAGE,
    DEFAULT_TAKER_FEE,
    assert_promotion_cost_ready,
    attach_cost_fidelity,
    build_funding_tca,
    extract_cost_grid,
    extract_funding_tca,
    grid_has_fee_slip,
    reject_zero_cost_only_go,
    require_cost_grid,
    require_dual_risk_report,
    require_funding_tca,
    summarize_measured_funding,
)
from quantflow.strategy.validation.paper_readiness import (
    PaperReadinessConfig,
    PaperReadinessError,
    _parse_ts,
    assert_paper_readiness,
    assert_report_paper_ready,
    check_paper_readiness,
    extract_paper_evidence,
    measure_fills,
    measure_orders,
    measure_paper_days,
)


def _grid_row(fee: float, slip: float, **extra) -> dict:
    row = {"taker_fee": fee, "slippage": slip}
    row.update(extra)
    return row


def _default_grid() -> list[dict]:
    return [_grid_row(0.0, 0.0, sharpe=1.2, return_pct=20.0), _grid_row(0.001, 0.001, sharpe=0.6, return_pct=8.0)]


# ---------------------------------------------------------------------------
# paper_readiness: config
# ---------------------------------------------------------------------------
class TestPaperReadinessConfig:
    def test_from_mapping_none_and_empty(self) -> None:
        assert PaperReadinessConfig.from_mapping(None) == PaperReadinessConfig()
        assert PaperReadinessConfig.from_mapping({}) == PaperReadinessConfig()

    def test_from_mapping_overrides(self) -> None:
        cfg = PaperReadinessConfig.from_mapping(
            {"enabled": False, "min_paper_days": "3.5", "min_fills": "5", "min_orders": "2", "require_evidence": False}
        )
        assert cfg.enabled is False
        assert cfg.min_paper_days == 3.5
        assert cfg.min_fills == 5
        assert cfg.min_orders == 2
        assert cfg.require_evidence is False

    def test_to_dict_roundtrip(self) -> None:
        d = PaperReadinessConfig().to_dict()
        assert d["min_paper_days"] == 7.0
        assert d["enabled"] is True


# ---------------------------------------------------------------------------
# paper_readiness: _parse_ts
# ---------------------------------------------------------------------------
class TestParseTs:
    def test_none_and_empty(self) -> None:
        assert _parse_ts(None) is None
        assert _parse_ts("") is None
        assert _parse_ts("   ") is None

    def test_datetime_aware_and_naive(self) -> None:
        aware = datetime(2024, 1, 1, tzinfo=UTC)
        assert _parse_ts(aware) is aware
        naive = datetime(2024, 1, 1)
        assert _parse_ts(naive).tzinfo == UTC

    def test_iso_trailing_z_and_plain(self) -> None:
        z = _parse_ts("2024-01-01T00:00:00Z")
        assert z.tzinfo is not None
        plain = _parse_ts("2024-01-01T00:00:00")
        assert plain.tzinfo == UTC

    def test_invalid_returns_none(self) -> None:
        assert _parse_ts("not-a-date") is None

    def test_int_seconds_passthrough_text(self) -> None:
        assert _parse_ts(1700000000) is None  # bare numeric not a datetime/text


# ---------------------------------------------------------------------------
# paper_readiness: extract / measure helpers
# ---------------------------------------------------------------------------
class TestExtractMeasure:
    def test_extract_paper_evidence_not_dict(self) -> None:
        assert extract_paper_evidence(None) is None
        assert extract_paper_evidence("nope") is None

    def test_extract_nested_validation(self) -> None:
        report = {"validation": {"paper_evidence": {"paper_days": 9.0}}}
        assert extract_paper_evidence(report) == {"paper_days": 9.0}

    def test_extract_skips_empty_blocks(self) -> None:
        report = {"paper_evidence": {}, "paper_stats": {"n": 1}}
        assert extract_paper_evidence(report) == {"n": 1}

    def test_measure_paper_days_key_and_conversion_failure(self) -> None:
        assert measure_paper_days({"paper_days": "8.5"}) == 8.5
        assert measure_paper_days({"days": 2}) == 2.0
        assert measure_paper_days({"paper_days": "junk"}) is None

    def test_measure_paper_days_timestamps_and_ms(self) -> None:
        assert measure_paper_days(
            {"started_at": "2024-01-01T00:00:00Z", "ended_at": "2024-01-08T00:00:00Z"}
        ) == pytest.approx(7.0)
        assert measure_paper_days({"start_ms": 0, "end_ms": 86_400_000}) == pytest.approx(1.0)
        # invalid ms conversion -> None
        assert measure_paper_days({"start_ms": "x", "end_ms": 1}) is None

    def test_measure_fills_and_orders(self) -> None:
        assert measure_fills({"n_fills": 30}) == 30
        assert measure_fills({"fills": "bad"}) is None
        assert measure_fills({}) is None
        assert measure_orders({"order_count": 4}) == 4
        assert measure_orders({"orders": "bad"}) is None
        assert measure_orders({}) is None


# ---------------------------------------------------------------------------
# paper_readiness: check / assert
# ---------------------------------------------------------------------------
class TestPaperReadinessChecks:
    def test_disabled_skips(self) -> None:
        out = check_paper_readiness(None, config=PaperReadinessConfig(enabled=False))
        assert out["skipped"] is True
        assert out["passed"] is True

    def test_no_evidence_require_false(self) -> None:
        out = check_paper_readiness(None, config=PaperReadinessConfig(require_evidence=False))
        assert out["passed"] is True

    def test_no_evidence_require_true(self) -> None:
        out = check_paper_readiness(None)
        assert out["passed"] is False
        assert any("missing" in r for r in out["reasons"])

    def test_days_unmeasurable_plus_fills_unmeasurable(self) -> None:
        out = check_paper_readiness({"fills": 25})
        assert out["passed"] is False
        assert any("paper_days unmeasurable" in r for r in out["reasons"])

    def test_days_below_min_and_fills_below_min(self) -> None:
        out = check_paper_readiness(
            {"paper_days": 2.0, "fills": 3},
            config=PaperReadinessConfig(min_paper_days=7.0, min_fills=20),
        )
        assert out["passed"] is False
        assert any("< min_paper_days" in r for r in out["reasons"])
        assert any("< min_fills" in r for r in out["reasons"])

    def test_orders_enforced_below_min(self) -> None:
        out = check_paper_readiness(
            {"paper_days": 8.0, "fills": 25, "orders": 1},
            config=PaperReadinessConfig(min_orders=2),
        )
        assert out["passed"] is False
        assert any("< min_orders" in r for r in out["reasons"])

    def test_orders_enforced_unmeasurable(self) -> None:
        out = check_paper_readiness(
            {"paper_days": 8.0, "fills": 25},
            config=PaperReadinessConfig(min_orders=2),
        )
        assert any("orders unmeasurable" in r for r in out["reasons"])

    def test_pass_happy_path(self) -> None:
        out = check_paper_readiness({"paper_days": 8.0, "fills": 25, "orders": 5})
        assert out["passed"] is True
        assert out["measured"]["paper_days"] == 8.0

    def test_assert_raises_on_fail_and_returns_on_pass(self) -> None:
        with pytest.raises(PaperReadinessError):
            assert_paper_readiness(None)
        out = assert_paper_readiness({"paper_days": 9.0, "fills": 30})
        assert out["passed"] is True

    def test_assert_report_ready_when_missing_override(self) -> None:
        # require_when_missing=False -> cfg.require_evidence=False -> pass w/o evidence
        out = assert_report_paper_ready(
            {"decision": "GO"},
            require_when_missing=False,
        )
        assert out["passed"] is True
        # require_when_missing=True -> fail closed
        with pytest.raises(PaperReadinessError):
            assert_report_paper_ready({"decision": "GO"}, require_when_missing=True)

    def test_assert_report_picks_evidence(self) -> None:
        out = assert_report_paper_ready(
            {"paper_evidence": {"paper_days": 10.0, "fills": 50}},
            require_when_missing=True,
        )
        assert out["passed"] is True


# ---------------------------------------------------------------------------
# cost_fidelity: grid extraction
# ---------------------------------------------------------------------------
class TestExtractCostGrid:
    def test_not_dict(self) -> None:
        assert extract_cost_grid(None) is None

    def test_top_level_keys(self) -> None:
        grid = _default_grid()
        assert extract_cost_grid({"fee_slip_grid": grid}) == grid
        assert extract_cost_grid({"cost_grid": grid}) == grid
        assert extract_cost_grid({"fee_slip": grid}) == grid

    def test_cost_fidelity_and_checks_nesting(self) -> None:
        grid = _default_grid()
        assert extract_cost_grid({"cost_fidelity": {"fee_slip_grid": grid}}) == grid
        assert extract_cost_grid({"checks": {"cost_fidelity": {"cost_grid": grid}}}) == grid

    def test_none_when_no_grid(self) -> None:
        assert extract_cost_grid({"decision": "GO"}) is None


class TestGridHasFeeSlip:
    def test_matches_and_missing_keys(self) -> None:
        assert grid_has_fee_slip([{"fee": 0.001, "slip": 0.001}], fee=0.001, slip=0.001) is True
        assert grid_has_fee_slip([{"taker_fee": 0.0, "slippage": 0.0}], fee=0.0, slip=0.0) is True

    def test_non_dict_row(self) -> None:
        assert grid_has_fee_slip(["junk", {}], fee=0.0, slip=0.0) is False

    def test_bad_numeric_row_continues(self) -> None:
        assert grid_has_fee_slip([{"taker_fee": "xx", "slippage": "yy"}], fee=0.0, slip=0.0) is False

    def test_no_match(self) -> None:
        assert grid_has_fee_slip([_grid_row(0.002, 0.002)], fee=0.001, slip=0.001) is False


# ---------------------------------------------------------------------------
# cost_fidelity: require_cost_grid / reject_zero_cost_only_go
# ---------------------------------------------------------------------------
class TestRequireCostGrid:
    def test_missing_grid_raises(self) -> None:
        with pytest.raises(CostFidelityError, match="missing"):
            require_cost_grid({"decision": "GO"})

    def test_missing_zero_cell(self) -> None:
        with pytest.raises(CostFidelityError, match="zero-cost"):
            require_cost_grid({"fee_slip_grid": [_grid_row(0.001, 0.001)]})

    def test_missing_production_cell(self) -> None:
        with pytest.raises(CostFidelityError, match="production"):
            require_cost_grid({"fee_slip_grid": [_grid_row(0.0, 0.0)]})

    def test_relaxed_flag(self) -> None:
        grid = require_cost_grid({"fee_slip_grid": [_grid_row(0.0, 0.0)]}, require_zero_and_default=False)
        assert len(grid) == 1

    def test_ok(self) -> None:
        assert require_cost_grid({"fee_slip_grid": _default_grid()}) == _default_grid()


class TestRejectZeroCostOnlyGo:
    def test_no_grid(self) -> None:
        with pytest.raises(CostFidelityError, match="cannot assess"):
            reject_zero_cost_only_go({"decision": "GO"})

    def test_missing_zero_or_prod(self) -> None:
        with pytest.raises(CostFidelityError, match="missing zero"):
            reject_zero_cost_only_go({"fee_slip_grid": [_grid_row(0.0, 0.0)]})

    def test_zero_cost_only_flag(self) -> None:
        with pytest.raises(CostFidelityError, match="zero_cost_only_go flag"):
            reject_zero_cost_only_go(
                {"fee_slip_grid": _default_grid(), "zero_cost_only_go": True}
            )

    def test_zero_positive_prod_missing(self) -> None:
        # zero cell has strong sharpe, prod cell present but sharpe missing -> refuse
        with pytest.raises(CostFidelityError, match="zero-cost-only GO refused"):
            reject_zero_cost_only_go(
                {
                    "fee_slip_grid": [
                        _grid_row(0.0, 0.0, sharpe=1.2),
                        _grid_row(0.001, 0.001),
                    ]
                }
            )

    def test_zero_return_positive_prod_zero(self) -> None:
        with pytest.raises(CostFidelityError, match="zero-cost-only GO refused"):
            reject_zero_cost_only_go(
                {
                    "fee_slip_grid": [
                        _grid_row(0.0, 0.0, return_pct=20.0),
                        _grid_row(0.001, 0.001, return_pct=0.0),
                    ]
                }
            )

    def test_passes_when_prod_positive(self) -> None:
        reject_zero_cost_only_go({"fee_slip_grid": _default_grid()})


# ---------------------------------------------------------------------------
# cost_fidelity: dual risk report
# ---------------------------------------------------------------------------
class TestDualRiskReport:
    def test_non_dict_report(self) -> None:
        with pytest.raises(CostFidelityError, match="dual risk report missing"):
            require_dual_risk_report(None)

    def test_too_few_rows(self) -> None:
        with pytest.raises(CostFidelityError, match="dual risk report"):
            require_dual_risk_report({"risk_ablation": [{"case": "research_bypass"}]})

    def test_cost_fidelity_nested_rows(self) -> None:
        rows = [
            {"case": "research_bypass"},
            {"case": "prod_risk"},
        ]
        out = require_dual_risk_report({"cost_fidelity": {"risk_ablation": rows}})
        assert len(out) == 2

    def test_boolean_pair_acceptance(self) -> None:
        rows = [
            {"research_risk_bypass": True},
            {"research_risk_bypass": False},
        ]
        out = require_dual_risk_report({"risk_ablation": rows})
        assert out == rows

    def test_incomplete_names_and_bools_raise(self) -> None:
        with pytest.raises(CostFidelityError, match="incomplete"):
            require_dual_risk_report(
                {"risk_ablation": [{"case": "a"}, {"case": "b"}]}
            )


# ---------------------------------------------------------------------------
# cost_fidelity: funding TCA
# ---------------------------------------------------------------------------
class TestFundingTca:
    def test_extract_nesting(self) -> None:
        block = build_funding_tca(mode="assumption")
        assert extract_funding_tca({"funding_tca": block}) is block
        assert extract_funding_tca({"tca": block}) is block
        assert extract_funding_tca({"cost_fidelity": {"tca": block}}) is block
        assert extract_funding_tca({"checks": {"cost_fidelity": {"funding_tca": block}}}) is block
        assert extract_funding_tca({"decision": "GO"}) is None

    def test_build_invalid_mode(self) -> None:
        with pytest.raises(CostFidelityError, match="mode"):
            build_funding_tca(mode="bogus")

    def test_build_taker_share_out_of_range(self) -> None:
        with pytest.raises(CostFidelityError, match="taker_share"):
            build_funding_tca(taker_share=1.5)

    def test_build_measured_uses_key(self) -> None:
        block = build_funding_tca(
            mode="measured",
            measured={"mean_abs_rate": 0.0002},
        )
        assert block["source"] == "measured"
        assert block["effective_abs_funding_per_event"] == 0.0002

    def test_build_measured_bad_value_continues(self) -> None:
        with pytest.raises(CostFidelityError, match="measured"):
            build_funding_tca(mode="measured", measured={"mean_abs_rate": "nope"})

    def test_build_measured_missing_dict(self) -> None:
        with pytest.raises(CostFidelityError, match="requires measured stats"):
            build_funding_tca(mode="measured")

    def test_build_hybrid_falls_back_to_assumption(self) -> None:
        block = build_funding_tca(mode="hybrid", measured=None)
        assert block["source"] == "assumption"
        block2 = build_funding_tca(mode="hybrid", measured={"abs_mean": 0.0001})
        assert block2["source"] == "measured"

    def test_require_funding_tca_missing(self) -> None:
        with pytest.raises(CostFidelityError, match="funding_tca missing"):
            require_funding_tca({"decision": "GO"})

    def test_require_funding_tca_invalid_mode(self) -> None:
        with pytest.raises(CostFidelityError, match="mode invalid"):
            require_funding_tca({"funding_tca": {"mode": "weird"}})

    def test_require_funding_tca_incomplete(self) -> None:
        with pytest.raises(CostFidelityError, match="incomplete"):
            require_funding_tca({"funding_tca": {"mode": "assumption", "notes": "x"}})

    def test_require_funding_tca_ok(self) -> None:
        require_funding_tca({"funding_tca": build_funding_tca()})

    def test_summarize_empty_raises(self) -> None:
        with pytest.raises(CostFidelityError, match="empty"):
            summarize_measured_funding([])

    def test_summarize_stats(self) -> None:
        out = summarize_measured_funding([0.0001, -0.0002], symbol="BTC/USDT", n_events=10)
        assert out["n_events"] == 10
        assert out["max_abs_rate"] == pytest.approx(0.0002)


# ---------------------------------------------------------------------------
# cost_fidelity: attach / assert gate
# ---------------------------------------------------------------------------
class TestAttachAndGate:
    def test_attach_without_optional_blocks(self) -> None:
        out = attach_cost_fidelity(  # noqa: SIM115
            {"decision": "GO"}, fee_slip_grid=_default_grid()
        )
        assert out["checks"]["cost_fidelity"]["passed"] is True
        assert "risk_ablation" not in out

    def test_attach_with_all_blocks(self) -> None:
        out = attach_cost_fidelity(
            {"decision": "GO"},
            fee_slip_grid=_default_grid(),
            risk_ablation=[{"case": "research_bypass"}, {"case": "prod_risk"}],
            funding_tca=build_funding_tca(),
        )
        assert out["risk_ablation"]
        assert out["funding_tca"]["mode"] == "assumption"

    def test_assert_promotion_cost_ready_ok(self) -> None:
        report = attach_cost_fidelity(
            {"decision": "GO", "execution_path": "paper_replay", "data_fingerprint": "abc123"},
            fee_slip_grid=_default_grid(),
            funding_tca=build_funding_tca(),
        )
        assert_promotion_cost_ready(report, require_funding=True, require_execution_path=True)

    def test_assert_promotion_cost_ready_missing_funding(self) -> None:
        report = attach_cost_fidelity(
            {"execution_path": "paper_replay"}, fee_slip_grid=_default_grid()
        )
        with pytest.raises(CostFidelityError):
            assert_promotion_cost_ready(report)

    def test_assert_promotion_cost_ready_bad_path(self) -> None:
        report = attach_cost_fidelity(
            {"execution_path": "backtest_engine", "data_fingerprint": "x"},
            fee_slip_grid=_default_grid(),
            funding_tca=build_funding_tca(),
        )
        with pytest.raises(CostFidelityError):
            assert_promotion_cost_ready(report)

    def test_defaults_match_documented(self) -> None:
        assert DEFAULT_TAKER_FEE == 0.001
        assert DEFAULT_SLIPPAGE == 0.001