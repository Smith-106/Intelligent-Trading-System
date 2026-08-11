"""B5 EMA-off / OI-off ablation: strategy knobs + contract discipline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quantflow.strategy.templates.funding_rate import FundingRateStrategy


def _df_with_extreme_rate() -> pd.DataFrame:
    n = 40
    rates = [0.0] * n
    rates[-1] = 0.001  # raw extreme > 0.0004
    oi = [100.0 + i * 0.1 for i in range(n)]  # mild rise, not 5%
    return pd.DataFrame(
        {
            "close": [100.0 + i * 0.01 for i in range(n)],
            "funding_rate": rates,
            "open_interest": oi,
        }
    )


class TestB5StrategyKnobs:
    def test_defaults_preserve_ema_and_oi(self) -> None:
        s = FundingRateStrategy()
        assert s._use_rate_ema is True
        assert s._require_oi_confirmation is True

    def test_ema_off_raw_rate_can_signal_without_oi(self) -> None:
        s = FundingRateStrategy(
            {
                "entry_threshold": 0.0004,
                "exit_threshold": 0.00015,
                "use_rate_ema": False,
                "require_oi_confirmation": False,
                "rate_ema_period": 8,
                "oi_lookback": 3,
            }
        )
        df = _df_with_extreme_rate()
        entries, _exits = s.generate_signals(df)
        assert bool(entries.iloc[-1]) is True

    def test_oi_on_blocks_without_oi_move(self) -> None:
        s = FundingRateStrategy(
            {
                "entry_threshold": 0.0004,
                "use_rate_ema": False,
                "require_oi_confirmation": True,
                "oi_lookback": 3,
                "oi_change_threshold": 0.05,
            }
        )
        df = _df_with_extreme_rate()
        # flat OI → no 5% change
        df["open_interest"] = 100.0
        entries, _ = s.generate_signals(df)
        assert bool(entries.iloc[-1]) is False

    def test_ema_on_smooths_single_spike(self) -> None:
        s = FundingRateStrategy(
            {
                "entry_threshold": 0.0004,
                "use_rate_ema": True,
                "require_oi_confirmation": False,
                "rate_ema_period": 8,
            }
        )
        df = _df_with_extreme_rate()
        entries, _ = s.generate_signals(df)
        # single-bar spike with span=8 usually fails to clear thr after EMA
        assert bool(entries.iloc[-1]) is False


class TestB5ContractArtifacts:
    def test_docs_and_overlay_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        assert (root / "docs" / "research" / "Candidate-Baseline-5.md").is_file()
        ov = (
            root
            / "quantflow"
            / "config"
            / "research"
            / "overlays"
            / "funding_rate_b5_overlay.yaml"
        )
        text = ov.read_text(encoding="utf-8")
        assert "0.0004" in text
        assert "use_rate_ema" in text
        assert "B3" in text and "B4" in text

    def test_b3_b4_yaml_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        b3 = (root / "quantflow" / "config" / "strategies" / "funding_rate.yaml").read_text(
            encoding="utf-8"
        )
        assert "entry_threshold: 0.001" in b3
        b4 = (
            root
            / "quantflow"
            / "config"
            / "research"
            / "overlays"
            / "funding_rate_b4_overlay.yaml"
        ).read_text(encoding="utf-8")
        assert "0.0004" in b4
        assert "use_rate_ema" not in b4  # B4 never set ablation knobs

    def test_runner_refuses_baseline3_4_paths(self) -> None:
        import scripts.run_baseline5_ablation_oos as b5

        with pytest.raises(SystemExit):
            b5._assert_path(Path("data/paper_replay/baseline3/x"))
        with pytest.raises(SystemExit):
            b5._assert_path(Path("data/paper_replay/baseline4/B4-OOS-20260810"))

    def test_index_lists_b5_when_results_written(self) -> None:
        root = Path(__file__).resolve().parents[2]
        # results may be written after OOS; contract doc must reference B5-ABL
        doc = (root / "docs" / "research" / "Candidate-Baseline-5.md").read_text(
            encoding="utf-8"
        )
        assert "B5-ABL-20260810" in doc
        assert "use_rate_ema" in doc
