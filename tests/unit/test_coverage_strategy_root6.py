"""Coverage completion (round 6) for strategy files B–E.

- quantflow/strategy/ai_validation_bypass.py  (L151/158-160/162-169/185-186/189-191/213-239)
- quantflow/strategy/catalog.py              (error/fallback paths of the YAML loader)
- quantflow/strategy/rd_agent.py             (CLI/availability/baseline branches)
- quantflow/strategy/elliott_wave_strategy.py (on_bar emission, degraded pivots, rule guards)

External integrations (qlib, rdagent CLI, transformers, training pipeline) are
mocked per the project unit-test convention.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Direction
from quantflow.strategy.ai_validation_bypass import AI_LANE, run_ai_validation_bypass
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy
from quantflow.strategy.rd_agent import (
    DiscoveredFactor,
    RDAgentCliUnavailableError,
    RDAgentRunner,
    load_discovered_factors,
    materialize_factor_frame,
)
from quantflow.indicators.wave_models import WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotDirection, PivotPoint


# --------------------------------------------------------------------------- #
# A. ai_validation_bypass.py
# --------------------------------------------------------------------------- #

def _ohlcv(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": rng.random(n) + 1.0,
            "timestamp": (idx.astype(np.int64) // 10**6).astype(np.int64),
        },
        index=idx,
    )


def _trained(**overrides):
    payload = {"decision": "GO", "n_samples": 60, "features_hash": "h1", "model_cls": "X"}
    payload.update(overrides)
    return SimpleNamespace(features_hash=payload["features_hash"], to_dict=lambda: dict(payload))


class TestAiValidationBypassBranches:
    @staticmethod
    def _install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple:
        import quantflow.strategy.ai_training as training_mod
        import quantflow.strategy.ai_validation_bypass as bypass
        import quantflow.strategy.rd_agent as rd

        monkeypatch.setattr(bypass, "BYPASS_REPORT_DIR", tmp_path / "ai_reports")
        monkeypatch.setattr(rd, "FACTORS_DIR", tmp_path / "ai_factors")
        return bypass, rd, training_mod

    @staticmethod
    def _stub_pipeline(monkeypatch: pytest.MonkeyPatch, training_mod, trained) -> MagicMock:
        pipe = MagicMock()
        pipe.train.return_value = trained
        monkeypatch.setattr(training_mod, "AITrainingPipeline", lambda **kw: pipe)
        return pipe

    def test_datetime_column_becomes_index(self, tmp_path, monkeypatch) -> None:
        """L151: ohlcv with 'datetime' column + non-DatetimeIndex → set_index."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        df = _ohlcv(40).reset_index(drop=True)
        df["datetime"] = pd.date_range("2024-01-01", periods=len(df), freq="h")
        captured: dict = {}

        def fake_materialize(frame, factors, *, selected_only):
            captured["index"] = frame.index
            return pd.DataFrame({"f1": [1.0] * len(frame)}, index=frame.index)

        monkeypatch.setattr(rd, "materialize_factor_frame", fake_materialize)
        monkeypatch.setattr(rd, "load_discovered_factors", lambda p: [])
        pipe = self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=df)
        assert isinstance(captured["index"], pd.DatetimeIndex)
        assert res.ai_lane == AI_LANE
        pipe.train.assert_called_once()

    def test_factors_json_loaded(self, tmp_path, monkeypatch) -> None:
        """L158-160: explicit factors_json exists → loaded."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        factors_file = tmp_path / "factors.json"
        factors_file.write_text(
            json.dumps(
                {"factors": [{"name": "momentum_5", "formula": "pandas:momentum_5", "selected": True}]}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame({"m": [1.0] * len(df)}, index=df.index))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv(), factors_json=str(factors_file))
        assert res.n_factors == 1
        assert any("loaded factors" in n for n in res.notes)

    def test_skip_discover_latest_exists(self, tmp_path, monkeypatch) -> None:
        """L162-167: skip_discover with latest.json → loaded from disk."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        latest_dir = tmp_path / "ai_factors" / "BTC_USDT"
        latest_dir.mkdir(parents=True)
        (latest_dir / "latest.json").write_text(
            json.dumps({"factors": [{"name": "momentum_20", "formula": "pandas:momentum_20", "selected": False}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame({"m": [1.0] * len(df)}, index=df.index))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv(), skip_discover=True)
        assert res.n_factors == 1
        assert any("loaded latest" in n for n in res.notes)

    def test_skip_discover_no_latest(self, tmp_path, monkeypatch) -> None:
        """L169: skip_discover without latest.json → empty-set note."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame({"m": [1.0] * len(df)}, index=df.index))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv(), skip_discover=True)
        assert any("no latest factors" in n for n in res.notes)
        assert res.n_factors == 0

    def test_discover_available_no_baseline_note(self, tmp_path, monkeypatch) -> None:
        """L173-175 (False arc): runner available → no degrade note."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        monkeypatch.setattr(
            rd.RDAgentRunner, "check_available", staticmethod(lambda: (True, ""))
        )
        monkeypatch.setattr(rd.RDAgentRunner, "discover_factors", lambda self, df: [])
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame({"m": [1.0] * len(df)}, index=df.index))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv())
        assert not any("unavailable" in n for n in res.notes)

    def test_materialize_fallback_to_all_factors(self, tmp_path, monkeypatch) -> None:
        """L185-186: selected_only empty → fallback to all factors."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        empty = pd.DataFrame()
        full = pd.DataFrame({"m": [1.0, 2.0]}, index=[0, 1])
        monkeypatch.setattr(rd, "materialize_factor_frame", MagicMock(side_effect=[empty, full]))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv(), skip_discover=True)
        assert any("fell back to all factors" in n for n in res.notes)

    def test_synthetic_ret1_last_resort(self, tmp_path, monkeypatch) -> None:
        """L189-191: no factor columns at all → synthetic ret1 feature."""
        import quantflow.strategy.ai_validation_bypass as bypass

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame())
        pipe = self._stub_pipeline(monkeypatch, training_mod, _trained())
        res = run_ai_validation_bypass(symbol="BTC/USDT", ohlcv=_ohlcv(), skip_discover=True)
        assert any("synthetic ret1" in n for n in res.notes)
        features = pipe.train.call_args.args[0]
        assert "ret1" in features.columns

    def test_register_rejected_rewrites_stamped_entry(self, tmp_path, monkeypatch) -> None:
        """L213-239: register=True writes lane stamps back on the registry entry."""
        import quantflow.strategy.ai_validation_bypass as bypass
        import quantflow.strategy.model_registry as registry_mod

        _, rd, training_mod = self._install(monkeypatch, tmp_path)
        monkeypatch.setattr(rd, "materialize_factor_frame", lambda df, f, *, selected_only: pd.DataFrame({"m": [1.0] * len(df)}, index=df.index))
        self._stub_pipeline(monkeypatch, training_mod, _trained())
        fake_reg = MagicMock()
        fake_reg.register.return_value = {"model_id": "model-h1", "status": "rejected", "reason": "w14"}
        monkeypatch.setattr(registry_mod, "ModelRegistry", lambda *a, **k: fake_reg)
        registry_dir = tmp_path / "reg"
        res = run_ai_validation_bypass(
            symbol="BTC/USDT", ohlcv=_ohlcv(), register=True, registry_dir=str(registry_dir)
        )
        assert res.registered_status == "rejected"
        entry_file = registry_dir / "model-h1.json"
        assert entry_file.exists()
        stamped = json.loads(entry_file.read_text(encoding="utf-8"))
        assert stamped["ai_lane"] == AI_LANE
        assert stamped["ai_live_blocked"] is True


# --------------------------------------------------------------------------- #
# B. catalog.py
# --------------------------------------------------------------------------- #

class TestCatalogEdgeCases:
    @staticmethod
    def _catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import quantflow.strategy.catalog as catalog

        monkeypatch.setattr(catalog, "_STRATEGY_CONFIG_DIR", tmp_path)
        return catalog

    def test_overlay_skip_and_load_errors(self, tmp_path, monkeypatch) -> None:
        """L160-161, 164-166, 169-170, 174, 207-212: loader error/fallback paths."""
        catalog = self._catalog(monkeypatch, tmp_path)
        (tmp_path / "a_overlay.yaml").write_text("strategy: {name: trend_following}\n", encoding="utf-8")
        (tmp_path / "bad.yaml").write_text("strategy: [unclosed\n", encoding="utf-8")
        (tmp_path / "scalar.yaml").write_text("just a string\n", encoding="utf-8")
        (tmp_path / "nostrategy.yaml").write_text("strategy: [1, 2]\n", encoding="utf-8")
        defs = catalog.get_strategy_definitions()
        assert "trend_following" not in defs  # overlay skipped
        assert "nostrategy" not in defs  # no factory → orphan skip
        assert defs == {}

    def test_duplicate_meta_and_paramspace_fallbacks(self, tmp_path, monkeypatch) -> None:
        """L178-184, 189, 196: duplicate id, non-dict metadata/param_space."""
        catalog = self._catalog(monkeypatch, tmp_path)
        (tmp_path / "one.yaml").write_text(
            "strategy: {name: trend_following}\nmetadata: [1]\nparam_space: [1]\n",
            encoding="utf-8",
        )
        (tmp_path / "two.yaml").write_text("strategy: {name: trend_following}\n", encoding="utf-8")
        defs = catalog.get_strategy_definitions()
        assert list(defs) == ["trend_following"]
        assert defs["trend_following"].param_space == {}

    def test_hygiene_error_paths(self, tmp_path, monkeypatch) -> None:
        """L261, 264-265, 267, 270: hygiene loader error/fallback paths."""
        catalog = self._catalog(monkeypatch, tmp_path)
        (tmp_path / "a_overlay.yaml").write_text("strategy: {name: x}\n", encoding="utf-8")
        (tmp_path / "bad.yaml").write_text("a: [\n", encoding="utf-8")
        (tmp_path / "scalar.yaml").write_text("hello\n", encoding="utf-8")
        (tmp_path / "nostrategy.yaml").write_text("strategy: 42\n", encoding="utf-8")
        report = catalog.catalog_hygiene()
        assert report["kind"] == "catalog_hygiene"
        assert "nostrategy" in report["orphan_yaml"]


# --------------------------------------------------------------------------- #
# C. rd_agent.py
# --------------------------------------------------------------------------- #

class TestRdAgentBranches:
    @staticmethod
    def _df(n: int = 120) -> pd.DataFrame:
        idx = pd.date_range("2024-01-01", periods=n, freq="h")
        close = 100 * np.exp(np.cumsum(np.random.default_rng(2).standard_normal(n) * 0.01))
        return pd.DataFrame({"close": close}, index=idx)

    def test_check_available_true(self, monkeypatch) -> None:
        """L160: qlib importable → (True, '')."""
        monkeypatch.setitem(sys.modules, "qlib", types.ModuleType("qlib"))
        ok, msg = RDAgentRunner.check_available()
        assert ok is True
        assert msg == ""

    def test_cli_available_true(self, monkeypatch) -> None:
        """L172: rdagent on PATH → (True, path)."""
        monkeypatch.setattr("quantflow.strategy.rd_agent.shutil.which", lambda name: "C:/rdagent/rdagent.exe")
        ok, path = RDAgentRunner.cli_available()
        assert ok is True
        assert path == "C:/rdagent/rdagent.exe"

    def test_discover_cli_unavailable_degrades(self, monkeypatch) -> None:
        """L240-241: CLI invocation raises RDAgentCliUnavailableError → baseline."""
        runner = RDAgentRunner()
        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent")))
        monkeypatch.setattr(RDAgentRunner, "_llm_config_from_env", lambda self: {"backend": "litellm", "model": "m", "api_base": ""})
        monkeypatch.setattr(
            RDAgentRunner,
            "_run_rdagent_cli",
            lambda self, df, schema=None: (_ for _ in ()).throw(RDAgentCliUnavailableError("no cli")),
        )
        factors = runner.discover_factors(self._df())
        assert len(factors) == 5  # degraded to built-in baseline

    def test_discover_no_llm_credentials(self, monkeypatch) -> None:
        """L257: available + CLI present but no LLM creds → baseline info path."""
        runner = RDAgentRunner()
        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent")))
        monkeypatch.setattr(RDAgentRunner, "_llm_config_from_env", lambda self: None)
        factors = runner.discover_factors(self._df())
        assert len(factors) == 5

    def test_run_rdagent_cli_missing_cli_raises(self, monkeypatch) -> None:
        """L291-293: no CLI → RDAgentCliUnavailableError."""
        runner = RDAgentRunner()
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (False, "no cli")))
        with pytest.raises(RDAgentCliUnavailableError):
            runner._run_rdagent_cli(self._df(30))

    def test_run_rdagent_cli_success_env_and_skip_unnamed(self, monkeypatch, tmp_path) -> None:
        """L333-336 + L373: env vars set; payload rows without a name skipped."""
        runner = RDAgentRunner()
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent.exe")))
        monkeypatch.setattr(
            RDAgentRunner,
            "_llm_config_from_env",
            lambda self: {"backend": "litellm", "model": "gpt-x", "api_base": "http://x"},
        )
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "data" / "rdagent_work" / "factors_output.json"
        out.parent.mkdir(parents=True)
        out.write_text(
            json.dumps(
                [
                    {"name": "", "ic": 0.0},
                    {"name": "f1", "formula": "x", "ic": 0.05, "rank_ic": 0.04},
                ]
            ),
            encoding="utf-8",
        )
        fake_run = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=""))
        monkeypatch.setattr(subprocess, "run", fake_run)
        factors = runner._run_rdagent_cli(self._df(30))
        assert [f.name for f in factors] == ["f1"]
        env = fake_run.call_args.kwargs["env"]
        assert env["CHAT_MODEL"] == "gpt-x"
        assert env["OPENAI_API_BASE"] == "http://x"

    def test_run_rdagent_cli_unreadable_output(self, monkeypatch, tmp_path) -> None:
        """L366-367: unreadable CLI output → ValueError."""
        runner = RDAgentRunner()
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent.exe")))
        monkeypatch.setattr(
            RDAgentRunner,
            "_llm_config_from_env",
            lambda self: {"backend": "litellm", "model": "m", "api_base": ""},
        )
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "data" / "rdagent_work" / "factors_output.json"
        out.parent.mkdir(parents=True)
        out.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr=""))
        with pytest.raises(ValueError, match="unreadable"):
            runner._run_rdagent_cli(self._df(30))

    def test_baseline_short_series(self) -> None:
        """L413-414: <30 aligned rows → appended without IC computation."""
        runner = RDAgentRunner()
        factors = runner._evaluate_alpha158_factors(self._df(10))
        assert len(factors) == 5
        assert all(f.ic == 0.0 for f in factors)

    def test_load_discovered_factors_skips_non_dict(self, tmp_path) -> None:
        """L501: non-dict payload rows skipped."""
        p = tmp_path / "f.json"
        p.write_text(
            json.dumps({"factors": [42, {"name": "x", "formula": "pandas:momentum_5", "selected": True}]}),
            encoding="utf-8",
        )
        out = load_discovered_factors(p)
        assert [f.name for f in out] == ["x"]

    def test_materialize_empty_or_no_close(self) -> None:
        """L521: empty df / missing close → empty frame."""
        assert materialize_factor_frame(pd.DataFrame()).empty
        assert materialize_factor_frame(pd.DataFrame({"open": [1.0]}), []).empty

    def test_materialize_factors_none_uses_all(self) -> None:
        """L533: factors=None → full built-in catalog."""
        frame = materialize_factor_frame(self._df(40), None)
        assert set(frame.columns) == {
            "momentum_5", "momentum_20", "volatility_20", "range_20", "return_skew_20",
        }

    def test_materialize_unselected_skipped_and_empty(self) -> None:
        """L538 + L552: unselected factor dropped → empty frame with index."""
        df = self._df(40)
        factors = [DiscoveredFactor(name="momentum_5", formula="pandas:momentum_5", selected=False)]
        frame = materialize_factor_frame(df, factors, selected_only=True)
        assert frame.empty
        assert list(frame.index) == list(df.index)

    def test_materialize_unknown_formula_skipped(self) -> None:
        """L543-548: non-materializable formula → warning + skip."""
        df = self._df(40)
        factors = [DiscoveredFactor(name="custom", formula="custom_expr")]
        frame = materialize_factor_frame(df, factors, selected_only=False)
        assert frame.empty


# --------------------------------------------------------------------------- #
# D. elliott_wave_strategy.py
# --------------------------------------------------------------------------- #

def _pp(idx: int, price: float) -> PivotPoint:
    return PivotPoint(index=idx, price=price, direction=PivotDirection.HIGH)


def _seg(label: int, start: PivotPoint, end: PivotPoint) -> WaveSegment:
    return WaveSegment(label=label, start=start, end=end)


def _w5_waves() -> dict[int, WaveSegment]:
    return {
        3: _seg(3, _pp(5, 80.0), _pp(15, 140.0)),
        5: _seg(5, _pp(10, 90.0), _pp(30, 150.0)),
    }


class TestElliottOnBarEmission:
    def _strategy(self, monkeypatch: pytest.MonkeyPatch) -> LiuYudongWaveStrategy:
        s = LiuYudongWaveStrategy()
        s._bar_rows = [
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "timestamp": 1}
        ] * 24
        return s

    def _bar(self) -> SimpleNamespace:
        return SimpleNamespace(
            open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0, timestamp=1, symbol="BTC/USDT"
        )

    def test_on_bar_emits_flat_exit(self, monkeypatch) -> None:
        """L148-161: last-bar exit → FLAT signal emitted."""
        s = self._strategy(monkeypatch)
        entries = pd.Series(False, index=range(25))
        exits = pd.Series(False, index=range(25))
        exits.iloc[-1] = True
        monkeypatch.setattr(s, "generate_signals", lambda df: (entries, exits))
        emitted: list = []
        monkeypatch.setattr(s, "emit_signal", lambda sig: emitted.append(sig), raising=False)
        s.on_bar(ctx=None, bar=self._bar())
        assert len(emitted) == 1
        assert emitted[0].direction == Direction.FLAT

    def test_on_bar_emits_long_entry(self, monkeypatch) -> None:
        """L162-171: last-bar entry (no exit) → LONG signal emitted."""
        s = self._strategy(monkeypatch)
        entries = pd.Series(False, index=range(25))
        entries.iloc[-1] = True
        exits = pd.Series(False, index=range(25))
        monkeypatch.setattr(s, "generate_signals", lambda df: (entries, exits))
        emitted: list = []
        monkeypatch.setattr(s, "emit_signal", lambda sig: emitted.append(sig), raising=False)
        s.on_bar(ctx=None, bar=self._bar())
        assert len(emitted) == 1
        assert emitted[0].direction == Direction.LONG


class TestElliottGenerateSignalsBranches:
    @staticmethod
    def _df(n: int = 120) -> pd.DataFrame:
        idx = range(n)
        return pd.DataFrame(
            {
                "open": [100.0] * n,
                "high": [101.0] * n,
                "low": [99.0] * n,
                "close": [100.5] * n,
                "volume": [1000.0] * n,
            },
            index=idx,
        )

    def _mocked(self, monkeypatch: pytest.MonkeyPatch, waves: dict[int, WaveSegment], pattern=WavePattern.IMPULSE):
        s = LiuYudongWaveStrategy()
        monkeypatch.setattr(s, "_detect_pivots", lambda df: MagicMock())
        wc = SimpleNamespace(pattern=pattern, waves=waves)
        monkeypatch.setattr(s.wave_identifier, "identify", lambda pivots, mode: wc)
        monkeypatch.setattr(s.fibonacci_calc, "calculate", lambda wc: SimpleNamespace(extension={}))
        monkeypatch.setattr(s.critical_level_det, "detect", lambda wc: MagicMock(levels=[]))
        monkeypatch.setattr(s.wave_channel, "calculate", lambda df, wc: SimpleNamespace(w5_target=None))
        monkeypatch.setattr(s.divergence_det, "detect", lambda wc, df: None)
        monkeypatch.setattr(s.invalidation_checker, "check", lambda wc, cl, lc: [])
        return s

    def test_degraded_pivots_skip_window(self, monkeypatch) -> None:
        """L205: _detect_pivots None → window skipped."""
        s = LiuYudongWaveStrategy()
        monkeypatch.setattr(s, "_detect_pivots", lambda df: None)
        entries, exits = s.generate_signals(self._df(60))
        assert entries.sum() == 0 and exits.sum() == 0

    def test_precomputed_indicator_columns(self, monkeypatch) -> None:
        """L219-221 + L221-224: macd/rsi columns already present → no recompute."""
        df = self._df(60)
        df["macd_histogram"] = 0.0
        df["rsi_14"] = 50.0
        s = self._mocked(monkeypatch, {})
        entries, exits = s.generate_signals(df)
        assert entries.sum() == 0 and exits.sum() == 0

    def test_w2_idx_out_of_new_window(self, monkeypatch) -> None:
        """L241-245: stale w2 end index outside new window → no entry."""
        waves = {2: _seg(2, _pp(0, 100.0), _pp(5, 110.0))}
        s = self._mocked(monkeypatch, waves)
        monkeypatch.setattr(s, "_check_w2_entry", lambda df, waves, bullish: True)
        entries, _ = s.generate_signals(self._df(120))
        assert entries.sum() == 1  # first window only (idx 5 in [0,20))

    def test_w3_missing_wave_1(self, monkeypatch) -> None:
        """L245-252: w3 check True but wave 1 absent → skip."""
        waves = {2: _seg(2, _pp(0, 100.0), _pp(5, 110.0))}
        s = self._mocked(monkeypatch, waves)
        monkeypatch.setattr(s, "_check_w2_entry", lambda df, waves, bullish: True)
        monkeypatch.setattr(s, "_check_w3_entry", lambda df, waves, bullish: True)
        entries, _ = s.generate_signals(self._df(120))
        assert entries.sum() == 1  # only the w2 entry from window 1

    def test_w3_idx_out_of_new_window(self, monkeypatch) -> None:
        """L248-252: stale w3 end index → no entry."""
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(3, 110.0)),
            3: _seg(3, _pp(3, 110.0), _pp(6, 130.0)),
        }
        s = self._mocked(monkeypatch, waves)
        monkeypatch.setattr(s, "_check_w3_entry", lambda df, waves, bullish: True)
        entries, _ = s.generate_signals(self._df(120))
        assert entries.sum() == 1  # window 1 only (idx 6 in [0,20))

    def test_w4_idx_out_of_new_window(self, monkeypatch) -> None:
        """L255-259: stale w4 end index → no entry."""
        waves = {
            3: _seg(3, _pp(0, 100.0), _pp(3, 120.0)),
            4: _seg(4, _pp(3, 120.0), _pp(6, 110.0)),
        }
        s = self._mocked(monkeypatch, waves)
        monkeypatch.setattr(s, "_check_w4_entry", lambda df, waves, bullish: True)
        entries, _ = s.generate_signals(self._df(120))
        assert entries.sum() == 1

    def test_w5_idx_out_of_new_window(self, monkeypatch) -> None:
        """L262-266: stale w5 end index → no exit."""
        waves = {5: _seg(5, _pp(0, 100.0), _pp(6, 140.0))}
        s = self._mocked(monkeypatch, waves)
        monkeypatch.setattr(s, "_check_w5_exit", lambda *a, **k: True)
        _, exits = s.generate_signals(self._df(120))
        assert exits.sum() == 1

    def test_corrective_bwave_check_false(self, monkeypatch) -> None:
        """L267-274: CORRECTIVE pattern with b-wave check False → skip."""
        s = self._mocked(monkeypatch, {5: _seg(5, _pp(0, 100.0), _pp(6, 140.0))}, pattern=WavePattern.CORRECTIVE)
        _, exits = s.generate_signals(self._df(120))
        assert exits.sum() == 0

    def test_corrective_bwave_missing_wave_m2(self, monkeypatch) -> None:
        """L268-274: b-wave check True but wave -2 absent → skip."""
        s = self._mocked(monkeypatch, {}, pattern=WavePattern.CORRECTIVE)
        monkeypatch.setattr(s, "_check_b_wave_exit", lambda df, waves: True)
        _, exits = s.generate_signals(self._df(120))
        assert exits.sum() == 0

    def test_corrective_bwave_idx_out_of_new_window(self, monkeypatch) -> None:
        """L270-274: stale -2 end index → no exit."""
        waves = {-2: _seg(-2, _pp(0, 100.0), _pp(6, 90.0))}
        s = self._mocked(monkeypatch, waves, pattern=WavePattern.CORRECTIVE)
        monkeypatch.setattr(s, "_check_b_wave_exit", lambda df, waves: True)
        _, exits = s.generate_signals(self._df(120))
        assert exits.sum() == 1


class TestElliottRuleHelpers:
    def test_w2_volume_nan_skips_filter(self) -> None:
        """L374-377: NaN volume averages → volume filter skipped."""
        s = LiuYudongWaveStrategy()
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(10, 120.0)),
            2: _seg(2, _pp(10, 120.0), _pp(20, 110.0)),
        }
        df = pd.DataFrame({"volume": [float("nan")] * 30})
        assert s._check_w2_entry(df, waves, True) is True

    def test_w2_volume_not_surge_fails_filter(self) -> None:
        """L375-377: w2 volume not above 0.8×w1 → passes."""
        s = LiuYudongWaveStrategy()
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(10, 120.0)),
            2: _seg(2, _pp(10, 120.0), _pp(20, 110.0)),
        }
        vol = [100.0] * 30
        for i in range(11, 20):
            vol[i] = 50.0
        df = pd.DataFrame({"volume": vol})
        assert s._check_w2_entry(df, waves, True) is True

    def test_w3_no_volume_column(self) -> None:
        """L392-399: no volume column → volume gate skipped."""
        s = LiuYudongWaveStrategy()
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(10, 120.0)),
            3: _seg(3, _pp(10, 120.0), _pp(20, 160.0)),
        }
        df = pd.DataFrame({"close": [100.0] * 30})
        assert s._check_w3_entry(df, waves, True) is True

    def test_w3_baseline_nan_skips(self) -> None:
        """L396-399: NaN 20-bar baseline volume → surge gate skipped."""
        s = LiuYudongWaveStrategy()
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(10, 120.0)),
            3: _seg(3, _pp(20, 120.0), _pp(30, 160.0)),
        }
        vol = [100.0] * 40
        vol[20] = float("nan")
        df = pd.DataFrame({"volume": vol})
        assert s._check_w3_entry(df, waves, True) is True

    def test_w3_surge_met_passes(self) -> None:
        """L397-399: avg volume >= surge threshold → passes."""
        s = LiuYudongWaveStrategy()
        waves = {
            1: _seg(1, _pp(0, 100.0), _pp(10, 120.0)),
            3: _seg(3, _pp(20, 120.0), _pp(30, 160.0)),
        }
        vol = [100.0] * 40
        for i in range(20, 30):
            vol[i] = 200.0
        df = pd.DataFrame({"volume": vol})
        assert s._check_w3_entry(df, waves, True) is True

    def test_w4_volume_nan_skips_filter(self) -> None:
        """L420-423: NaN volume averages → volume filter skipped."""
        s = LiuYudongWaveStrategy()
        waves = {
            3: _seg(3, _pp(0, 100.0), _pp(10, 140.0)),
            4: _seg(4, _pp(10, 140.0), _pp(20, 122.0)),
        }
        df = pd.DataFrame({"volume": [float("nan")] * 30})
        assert s._check_w4_entry(df, waves, True) is True

    def test_w4_volume_not_surge_fails_filter(self) -> None:
        """L421-423: w4 volume not above 0.8×w3 → passes."""
        s = LiuYudongWaveStrategy()
        waves = {
            3: _seg(3, _pp(0, 100.0), _pp(10, 140.0)),
            4: _seg(4, _pp(10, 140.0), _pp(20, 122.0)),
        }
        vol = [100.0] * 30
        for i in range(11, 20):
            vol[i] = 50.0
        df = pd.DataFrame({"volume": vol})
        assert s._check_w4_entry(df, waves, True) is True

    def test_w5_divergence_none_and_index_guard(self) -> None:
        """L439-443 + L446-452: no divergence; w5 end index out of df range."""
        s = LiuYudongWaveStrategy()
        df = pd.DataFrame({"volume": [1.0] * 20})
        channel = SimpleNamespace(w5_target=100.0)
        fib = SimpleNamespace(extension={1.618: 100.0})
        assert s._check_w5_exit(df, _w5_waves(), True, divergence=None, channel=channel, fib_levels=fib) is True

    def test_w5_volume_nan(self) -> None:
        """L449-452: NaN volume at wave ends → volume signal skipped."""
        s = LiuYudongWaveStrategy()
        df = pd.DataFrame({"volume": [float("nan")] * 40})
        assert s._check_w5_exit(df, _w5_waves(), True) is False

    def test_w5_volume_not_low(self) -> None:
        """L450-452: w5 volume not below 0.7×w3 → no volume signal."""
        s = LiuYudongWaveStrategy()
        vol = [1.0] * 40
        vol[15] = 100.0
        vol[30] = 80.0
        df = pd.DataFrame({"volume": vol})
        assert s._check_w5_exit(df, _w5_waves(), True) is False

    def test_w5_divergence_mismatch_still_exits(self) -> None:
        """L440-439: divergence item not matching wave 5 → loop continues."""
        s = LiuYudongWaveStrategy()
        df = pd.DataFrame({"volume": [1.0] * 40})
        divergence = SimpleNamespace(
            bearish=True, divergences=[SimpleNamespace(wave_ref=3, strength=0.9)]
        )
        channel = SimpleNamespace(w5_target=100.0)
        fib = SimpleNamespace(extension={1.618: 100.0})
        assert s._check_w5_exit(df, _w5_waves(), True, divergence=divergence, channel=channel, fib_levels=fib) is True

    def test_w5_fib_extension_missing(self) -> None:
        """L461-466: no 1.618 extension → fib signal skipped."""
        s = LiuYudongWaveStrategy()
        df = pd.DataFrame({"volume": [1.0] * 40})
        fib = SimpleNamespace(extension={})
        assert s._check_w5_exit(df, _w5_waves(), True, channel=None, fib_levels=fib) is False

    def test_w5_fib_target_not_reached(self) -> None:
        """L462-466: price below 0.98×extension → no fib signal."""
        s = LiuYudongWaveStrategy()
        df = pd.DataFrame({"volume": [1.0] * 40})
        fib = SimpleNamespace(extension={1.618: 200.0})
        assert s._check_w5_exit(df, _w5_waves(), True, channel=None, fib_levels=fib) is False

    def test_b_wave_volume_not_higher_passes(self) -> None:
        """L482-484: b-wave volume not above a-wave → passes."""
        s = LiuYudongWaveStrategy()
        waves = {
            -1: _seg(-1, _pp(0, 100.0), _pp(10, 80.0)),
            -2: _seg(-2, _pp(10, 80.0), _pp(20, 90.0)),
        }
        df = pd.DataFrame({"volume": [1.0] * 30})
        assert s._check_b_wave_exit(df, waves) is True
