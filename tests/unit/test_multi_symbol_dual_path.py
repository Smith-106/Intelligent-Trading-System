"""IMP-04 multi-symbol dual-path tests."""

from __future__ import annotations

import pytest

from quantflow.strategy.research.dual_path_report import assert_no_combined_score
from quantflow.strategy.research.multi_symbol_dual_path import (
    build_multi_symbol_dual_path_report,
    equal_book_weights,
    synth_ohlcv,
)


def test_equal_weights() -> None:
    w = equal_book_weights(["BTC/USDT", "ETH/USDT"])
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert w["BTC/USDT"] == pytest.approx(0.5)


def test_multi_symbol_report_no_combined_score() -> None:
    frames = {
        "BTC/USDT": synth_ohlcv(900, seed=1, drift=0.0003),
        "ETH/USDT": synth_ohlcv(900, seed=2, drift=0.0001),
    }
    rep = build_multi_symbol_dual_path_report(frames)
    assert rep["promotion_eligible"] is False
    assert len(rep["symbols"]) == 2
    assert rep["book"]["portfolio_traceable"] is True
    assert "combined_score" not in rep
    assert_no_combined_score(rep)
    assert rep["run_meta"]["execution_path"] == "vectorized"
    assert rep["attachments"]["promotion_path"]["register_ready"] is False
    for sym in rep["symbols"]:
        assert rep["per_symbol"][sym]["promotion_eligible"] is False
        assert "path_a" in rep["per_symbol"][sym]
        assert "path_b" in rep["per_symbol"][sym]


def test_requires_two_symbols() -> None:
    with pytest.raises(ValueError, match=">=2"):
        build_multi_symbol_dual_path_report({"BTC/USDT": synth_ohlcv(500)})
