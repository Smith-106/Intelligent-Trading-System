"""W14: promotion execution-path discipline."""

from __future__ import annotations

import pytest

from quantflow.strategy.validation.promotion_path import (
    PromotionPathError,
    assert_promotion_path_ready,
    attach_promotion_path,
    check_promotion_path,
    extract_execution_path,
)


def test_extract_path_from_checks():
    assert (
        extract_execution_path({"checks": {"execution_path": "Trading-Session"}})
        == "trading_session"
    )


def test_paper_replay_ok():
    r = assert_promotion_path_ready(
        {
            "execution_path": "paper_replay",
            "data_fingerprint": {"aggregate": "x"},
        }
    )
    assert r["passed"] is True


def test_missing_path():
    with pytest.raises(PromotionPathError, match="missing"):
        assert_promotion_path_ready({"decision": "GO"})


def test_vectorized_refused():
    with pytest.raises(PromotionPathError, match="research-filter"):
        assert_promotion_path_ready(
            {
                "execution_path": "backtest_engine",
                "data_fingerprint": "h",
            }
        )


def test_missing_fingerprint():
    with pytest.raises(PromotionPathError, match="fingerprint"):
        assert_promotion_path_ready({"execution_path": "paper_replay"})


def test_attach_helper():
    out = attach_promotion_path(
        {"decision": "GO"},
        execution_path="paper_replay",
        data_fingerprint={"aggregate": "z"},
    )
    assert out["execution_path"] == "paper_replay"
    assert check_promotion_path(out)["passed"] is True
