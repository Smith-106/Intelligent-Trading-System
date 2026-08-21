"""Coverage completion for research path modules:

- quantflow/strategy/research/path_b_oos.py
- quantflow/strategy/research/dual_path_profiles.py
- quantflow/strategy/research/dual_path_report.py
- quantflow/strategy/research/multi_symbol_dual_path.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research import dual_path_profiles as dpp
from quantflow.strategy.research import dual_path_report as dpr
from quantflow.strategy.research import multi_symbol_dual_path as msdp
from quantflow.strategy.research import path_b_oos as pbo

# ---------------------------------------------------------------------------
# path_b_oos
# ---------------------------------------------------------------------------


def _close_df(n: int = 800, *, with_timestamp: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n)))
    df = pd.DataFrame(
        {
            "close": close,
            "high": close * 1.002,
            "low": close * 0.998,
        }
    )
    if with_timestamp:
        df["timestamp"] = [i * 3_600_000 for i in range(n)]
    return df


def test_eval_path_b_slice_requires_close() -> None:
    with pytest.raises(ValueError, match="close"):
        pbo._eval_path_b_slice(
            pd.DataFrame({"x": [1.0]}),
            fast=10,
            slow=20,
            stop_loss_pct=0.04,
            take_profit_pct=0.1,
            min_rr=2.5,
            max_holding_bars=0,
            fee=0.001,
            slip=0.001,
        )


def test_is_select_params_breaks_at_max_candidates() -> None:
    """Cover the three nested `break` guards in _is_select_params."""
    df = _close_df(300, with_timestamp=False)
    space = {
        "stop_loss_pct": (0.04, 0.05, 0.06),
        "min_rr": (2.0, 2.5, 3.0, 3.5),
        "max_holding_bars": (0, 1, 2, 3, 4),
    }
    best = pbo._is_select_params(
        df, fast=96, slow=400, space=space, fee=0.001, slip=0.001, max_candidates=12
    )
    assert set(best) == {"stop_loss_pct", "min_rr", "take_profit_pct", "max_holding_bars"}


def test_is_select_params_skips_failing_candidates(monkeypatch) -> None:
    """Cover the except->continue guard in _is_select_params."""
    df = _close_df(300, with_timestamp=False)
    space = {"stop_loss_pct": (0.04, 0.05), "min_rr": (2.5,), "max_holding_bars": (0,)}

    def flaky(df_, **kwargs):
        if kwargs["stop_loss_pct"] == 0.05:
            raise RuntimeError("boom")
        return {"excess_return_pct": 1.0, "max_dd_pct": 2.0}

    monkeypatch.setattr(pbo, "_eval_path_b_slice", flaky)
    best = pbo._is_select_params(df, fast=96, slow=400, space=space, fee=0.001, slip=0.001)
    assert best["stop_loss_pct"] == 0.04


def test_run_path_b_oos_validations() -> None:
    df = _close_df(800)
    with pytest.raises(ValueError, match="close"):
        pbo.run_path_b_multi_window_oos(None)
    with pytest.raises(ValueError, match="n_windows"):
        pbo.run_path_b_multi_window_oos(df, n_windows=1)
    with pytest.raises(ValueError, match="oos_ratio"):
        pbo.run_path_b_multi_window_oos(df, n_windows=2, oos_ratio=0.9)


def test_run_path_b_oos_window_too_short_continues() -> None:
    """Small windows -> all folds skipped -> fail-closed ValueError."""
    df = _close_df(200)
    with pytest.raises(ValueError, match="no valid OOS windows"):
        pbo.run_path_b_multi_window_oos(df, n_windows=4, oos_ratio=0.3)


def test_run_path_b_oos_oos_size_too_small_continues() -> None:
    """fold passes the IS-length guard but oos_size <= 20 -> continue."""
    df = _close_df(400)
    with pytest.raises(ValueError, match="no valid OOS windows"):
        pbo.run_path_b_multi_window_oos(df, n_windows=4, oos_ratio=0.2)


def test_run_path_b_oos_fingerprint_fallback(monkeypatch) -> None:
    """fingerprint_ohlcv raising -> fallback_len aggregate."""
    from quantflow.strategy.research import contract_pin

    df = _close_df(800)

    def boom(_df):
        raise RuntimeError("no fp")

    monkeypatch.setattr(contract_pin, "fingerprint_ohlcv", boom)
    rep = pbo.run_path_b_multi_window_oos(
        df, n_windows=3, oos_ratio=0.3, fixed_params=True, claimed_n_trials=10
    )
    assert rep["data_fingerprint"]["source"] == "fallback_len"
    assert rep["data_fingerprint"]["aggregate"] == f"bars:{len(df)}"
    assert rep["promotion_eligible"] is False
    assert rep["summary"]["n_windows_eval"] == 3


def test_window_oos_result_to_dict() -> None:
    r = pbo.WindowOOSResult(
        window_id=0,
        is_start=0,
        is_end=10,
        oos_start=10,
        oos_end=20,
        oos_bars=10,
        excess_return_pct=1.0,
        max_dd_pct=2.0,
        winrate=0.5,
        payoff_ratio=1.5,
        n_trades=4,
        gate_vs_btc="PASS",
        best_params={"stop_loss_pct": 0.04},
        notes=["n"],
    )
    d = r.to_dict()
    assert d["window_id"] == 0 and d["notes"] == ["n"]


# ---------------------------------------------------------------------------
# dual_path_profiles
# ---------------------------------------------------------------------------


def test_default_yaml_path_exists() -> None:
    p = dpp.default_yaml_path()
    assert p.name == "dual_path_profiles.yaml"
    assert p.is_file()


def test_load_dual_path_profiles_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        dpp.load_dual_path_profiles(tmp_path / "nope.yaml")


def test_load_dual_path_profiles_root_not_mapping(tmp_path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        dpp.load_dual_path_profiles(f)


def test_load_dual_path_profiles_missing_key(tmp_path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text("path_a: {}\npath_b: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required key"):
        dpp.load_dual_path_profiles(f)


def test_load_dual_path_profiles_paths_not_mappings(tmp_path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text("path_a: [1]\npath_b: {}\ngates: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be mappings"):
        dpp.load_dual_path_profiles(f)


def test_path_a_profile_unknown_name_passes() -> None:
    cfg = {"path_a": {"name": "not_registered", "overlay_weight": 0.2}, "path_b": {}, "gates": {}}
    a = dpp.path_a_profile(cfg)
    assert a["kind"] == "continuous_overlay"
    assert a["overlay_weight"] == 0.2


def test_path_a_profile_partial_registered(monkeypatch) -> None:
    """Registered profile missing keys -> `if k in registered` False branch."""
    cfg = {"path_a": {"name": "primary_w30", "overlay_weight": 0.2}, "path_b": {}, "gates": {}}
    monkeypatch.setattr(dpp, "get_profile", lambda name: {"mode": "reduce_off"})
    a = dpp.path_a_profile(cfg)
    # overlay_weight not in the partial registry dict -> keeps own value
    assert a["overlay_weight"] == 0.2
    assert a["mode"] == "reduce_off"


def test_assert_aligned_with_primary_raises() -> None:
    from quantflow.strategy.research.btc_overlay_profiles import PRIMARY

    bad_weight = dict(PRIMARY)
    bad_weight["overlay_weight"] = 0.5
    with pytest.raises(AssertionError, match="overlay_weight"):
        dpp.assert_aligned_with_primary(bad_weight)

    bad_fast = dict(PRIMARY)
    bad_fast["fast"] = 100
    with pytest.raises(AssertionError, match="fast"):
        dpp.assert_aligned_with_primary(bad_fast)


def test_forbid_combined_score_default() -> None:
    assert dpp.forbid_combined_score_enabled({"path_a": {}, "path_b": {}, "gates": {}}) is True
    assert (
        dpp.forbid_combined_score_enabled(
            {"path_a": {}, "path_b": {}, "gates": {"forbid_combined_score": False}}
        )
        is False
    )


# ---------------------------------------------------------------------------
# dual_path_report
# ---------------------------------------------------------------------------


def _sample_report() -> dpr.DualPathResearchReport:
    return dpr.build_dual_path_report(
        path_a={"return_pct": 1.0, "excess_return_pct": 2.0},
        path_b={"return_pct": 0.5},
        attachments={"multi_symbol": {"symbols": ["A", "B"]}},
        data_fingerprint={"aggregate": "abc"},
    )


def test_to_markdown_with_attachments() -> None:
    md = dpr.to_markdown(_sample_report())
    assert "## Attachments" in md
    assert "- `multi_symbol`" in md


def test_to_markdown_without_attachments() -> None:
    """Cover the `if d.get("attachments")` False branch."""
    bare = dpr.DualPathResearchReport(paths={"path_a": {"return_pct": 1.0}, "path_b": {}})
    md = dpr.to_markdown(bare)
    assert "## Attachments" not in md


def test_write_report_without_markdown(tmp_path) -> None:
    jp, mp = dpr.write_report(_sample_report(), tmp_path / "out" / "r.json")
    assert jp.is_file()
    assert mp is None
    assert '"contract"' in jp.read_text(encoding="utf-8")


def test_write_report_with_markdown(tmp_path) -> None:
    jp, mp = dpr.write_report(_sample_report(), tmp_path / "r.json", out_md=tmp_path / "r.md")
    assert jp.is_file() and mp is not None and mp.is_file()


# ---------------------------------------------------------------------------
# multi_symbol_dual_path
# ---------------------------------------------------------------------------


def test_equal_book_weights_empty() -> None:
    assert msdp.equal_book_weights([]) == {}


def test_run_symbol_dual_path_requires_close() -> None:
    with pytest.raises(ValueError, match="close required"):
        msdp.run_symbol_dual_path(pd.DataFrame(), symbol="BTC/USDT")


def test_simulate_path_a_inserts_repo_root(monkeypatch) -> None:
    """Cover the sys.path.insert guard when repo root is absent from path."""
    root = str(Path(msdp.__file__).resolve().parents[3])
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != root])
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.005, 500))))
    out = msdp._simulate_path_a(
        close,
        {
            "overlay_weight": 0.3,
            "fee": 0.001,
            "slip": 0.001,
            "fast": 96,
            "slow": 400,
            "mode": "reduce_off",
        },
    )
    assert "primary_overlay_reduce_off" in out
    assert "hodl" in out


def test_multi_symbol_book_weighted_excess_skips_missing(monkeypatch) -> None:
    """Cover the `is not None` guards in the book-level weighted loop."""
    frames = {
        "A": msdp.synth_ohlcv(120, seed=1),
        "B": msdp.synth_ohlcv(120, seed=2),
        "C": msdp.synth_ohlcv(120, seed=3),
    }

    def stub(df, *, symbol, path_a=None, path_b=None):
        return {
            "symbol": symbol,
            "bars": len(df),
            "data_fingerprint": {"aggregate": f"fp-{symbol}", "symbol": symbol, "bars": len(df)},
            "path_a": {
                "kind": "continuous_overlay",
                "profile": {},
                "metrics": (
                    {}
                    if symbol == "B"
                    else {
                        "excess_return_pct": 3.0,
                        "return_pct": 2.0,
                        "max_dd_pct": 1.0,
                        "gate_vs_btc": "PASS",
                        "beats_btc": True,
                    }
                ),
                "promotion_eligible": False,
            },
            "path_b": {
                "kind": "discrete_tpsl",
                "profile": {},
                "metrics": {} if symbol == "C" else {"excess_return_pct": 1.0},
                "promotion_eligible": False,
            },
            "hodl": {},
            "promotion_eligible": False,
        }

    monkeypatch.setattr(msdp, "run_symbol_dual_path", stub)
    rep = msdp.build_multi_symbol_dual_path_report(frames)
    display = rep["attachments"]["multi_symbol"]["book_display"]
    # path_a: A contributes 3.0/3 and C contributes 3.0/3 (B skips);
    # path_b: A contributes 1.0/3 and B contributes 1.0/3 (C skips).
    assert display["weighted_path_a_excess_pct"] == pytest.approx(2.0)
    assert display["weighted_path_b_excess_pct"] == pytest.approx(2.0 / 3.0)
    assert rep["book"]["allocation_mode"] == "equal"
