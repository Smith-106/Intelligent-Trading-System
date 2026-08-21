"""CLI tail3: remaining cli/main.py commands (scaffold/scripts wrappers + ai branches)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from typer.testing import CliRunner

from quantflow.cli.main import app

runner = CliRunner()


def _df(n: int = 100) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )


# ---------------------------------------------------------------- new-strategy
class TestNewStrategyTail:
    def test_new_strategy_happy(self) -> None:
        fake_result = SimpleNamespace(
            strategy_id="my_alpha", class_name="MyAlphaStrategy", files_written=["a.py"]
        )
        with patch("quantflow.strategy.scaffold.scaffold_strategy", return_value=fake_result):
            result = runner.invoke(app, ["new-strategy", "my_alpha"])
        assert result.exit_code == 0
        assert "Scaffolded" in result.output

    def test_new_strategy_scaffold_error(self) -> None:
        from quantflow.strategy.scaffold import ScaffoldError

        with patch(
            "quantflow.strategy.scaffold.scaffold_strategy",
            side_effect=ScaffoldError("bad id"),
        ):
            result = runner.invoke(app, ["new-strategy", "my_alpha"])
        assert result.exit_code == 1
        assert "scaffold failed" in result.output


# -------------------------------------------------------------- assert-elliott
class TestAssertElliottTail:
    def test_assert_elliott_ok(self) -> None:
        with patch("scripts.assert_elliott_cost_package.main", return_value=0):
            result = runner.invoke(app, ["assert-elliott"])
        assert result.exit_code == 0
        assert "structure OK" in result.output

    def test_assert_elliott_fail(self) -> None:
        with patch("scripts.assert_elliott_cost_package.main", return_value=3):
            result = runner.invoke(app, ["assert-elliott"])
        assert result.exit_code == 3
        assert "assert-elliott failed" in result.output


# ------------------------------------------------------------------- freeze-b4
class TestFreezeB4Tail:
    def test_freeze_b4_ok(self) -> None:
        with patch("scripts.freeze_baseline4_adjudication.main", return_value=0):
            result = runner.invoke(app, ["freeze-b4", "--run-dir", "baseline4/run1"])
        assert result.exit_code == 0
        assert "B4 freeze written" in result.output

    def test_freeze_b4_fail(self) -> None:
        with patch("scripts.freeze_baseline4_adjudication.main", return_value=2):
            result = runner.invoke(app, ["freeze-b4", "--run-dir", "baseline4/run1"])
        assert result.exit_code == 2


# ------------------------------------------------------------ eval-btc-overlay
class TestEvalBtcOverlayTail:
    def test_eval_overlay_ok(self) -> None:
        with patch("scripts.run_btc_beta_overlay_eval.main", return_value=0):
            result = runner.invoke(app, ["eval-btc-overlay"])
        assert result.exit_code == 0
        assert "eval-btc-overlay written" in result.output

    def test_eval_overlay_sweep_fail(self) -> None:
        with patch("scripts.run_btc_beta_overlay_eval.main", return_value=1):
            result = runner.invoke(app, ["eval-btc-overlay", "--sweep"])
        assert result.exit_code == 1


# ------------------------------------------------------------------- kol-ingest
class TestKolIngestTail:
    def test_kol_export_ok(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=0):
            result = runner.invoke(app, ["kol-ingest", "export", "--path", "out.json"])
        assert result.exit_code == 0
        assert "kol-ingest export done" in result.output

    def test_kol_export_missing_path(self) -> None:
        result = runner.invoke(app, ["kol-ingest", "export"])
        assert result.exit_code == 2
        assert "--path required" in result.output

    def test_kol_export_with_images(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=0):
            result = runner.invoke(app, ["kol-ingest", "export", "--path", "out.json", "--images"])
        assert result.exit_code == 0

    def test_kol_poll_ok(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=0):
            result = runner.invoke(app, ["kol-ingest", "poll", "--channel", "c1", "--images"])
        assert result.exit_code == 0

    def test_kol_consensus_ok(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=0):
            result = runner.invoke(app, ["kol-ingest", "consensus"])
        assert result.exit_code == 0

    def test_kol_bad_action(self) -> None:
        result = runner.invoke(app, ["kol-ingest", "bogus"])
        assert result.exit_code == 2
        assert "action must be" in result.output

    def test_kol_script_fail(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=5):
            result = runner.invoke(app, ["kol-ingest", "consensus"])
        assert result.exit_code == 5


# ---------------------------------------------------------------------- status
class TestStatusTail:
    def test_status_docker_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1764-1765: docker subprocess fails → Not available."""
        import subprocess

        def _fake_run(*a, **k):
            raise FileNotFoundError("docker missing")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Not available" in result.output


# ------------------------------------------------------------- __main__ block
class TestMainBlockTail:
    def test_main_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L1787: `if __name__ == '__main__': app()`."""
        import runpy

        import typer

        called: list[str] = []

        def _fake_call(self: Any, *a: Any, **k: Any) -> None:
            called.append("app")

        monkeypatch.setattr(typer.Typer, "__call__", _fake_call)
        runpy.run_module("quantflow.cli.main", run_name="__main__")
        assert called == ["app"]


# ------------------------------------------------------------------ ai branches
class TestAiBranchesTail:
    def test_ai_train_latest_json_exists(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1285-1286: latest.json auto-discovery."""
        safe = "BTC_USDT"
        latest_dir = Path("data/ai_factors") / safe
        latest_dir.mkdir(parents=True, exist_ok=True)
        latest = latest_dir / "latest.json"
        latest.write_text(
            json.dumps({"factors": [{"name": "f1", "formula": "x"}]}), encoding="utf-8"
        )
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={},
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch(
                "quantflow.strategy.rd_agent.load_discovered_factors",
                return_value=[SimpleNamespace(name="f1", formula="x")],
            ),
            patch(
                "quantflow.strategy.rd_agent.materialize_factor_frame",
                return_value=_df().set_index("datetime")[["close"]].rename(columns={"close": "f1"}),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(app, ["ai", "train", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "Training from discovered factors" in result.output
        latest.unlink()

    def test_ai_train_factors_json_missing(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1292-1293: factors-json not found → fallback message."""
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={},
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        fake_fs = MagicMock()
        fake_fs.compute_features = MagicMock(
            return_value=_df().set_index("datetime")[["close"]].rename(columns={"close": "f1"})
        )
        raw_with_ts = _df()
        raw_with_ts["timestamp"] = [1700000000000 + i * 86400000 for i in range(len(raw_with_ts))]
        fake_store.query = MagicMock(return_value=raw_with_ts)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch("quantflow.indicators.engine.IndicatorEngine", return_value=MagicMock()),
            patch("quantflow.data.feature_store.FeatureStore", return_value=fake_fs),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(
                app,
                [
                    "ai",
                    "train",
                    "--symbol",
                    "BTC/USDT",
                    "--factors-json",
                    str(tmp_path / "missing.json"),
                ],
            )
        assert result.exit_code == 0
        assert "factors-json not found" in result.output

    def test_ai_train_empty_data(self) -> None:
        """L1285-1286: no features_csv + empty store → No data."""
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["ai", "train", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_ai_train_timestamp_drop(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1334: features with timestamp column and no close → drop."""
        fj = tmp_path / "factors.json"
        fj.write_text(json.dumps({"factors": [{"name": "f1", "formula": "x"}]}), encoding="utf-8")
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={},
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        feat = _df()
        feat["timestamp"] = [1700000000000 + i * 86400000 for i in range(len(feat))]
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch(
                "quantflow.strategy.rd_agent.load_discovered_factors",
                return_value=[SimpleNamespace(name="f1", formula="x")],
            ),
            patch(
                "quantflow.strategy.rd_agent.materialize_factor_frame",
                return_value=feat.set_index("datetime")[["timestamp"]],
            ),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(
                app,
                [
                    "ai",
                    "train",
                    "--symbol",
                    "BTC/USDT",
                    "--factors-json",
                    str(fj),
                ],
            )
        assert result.exit_code == 0
        assert "Training from discovered factors" in result.output

    def test_ai_register_ic_gate_fail(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1425-1427: IC below threshold → NO-GO."""
        report_dir = tmp_path / "data" / "ai_reports"
        report_dir.mkdir(parents=True)
        (report_dir / "model-abc.json").write_text(
            json.dumps(
                {
                    "model_id": "model-abc",
                    "model_cls": "X",
                    "features_hash": "abc",
                    "decision": "GO",
                    "ic_metrics": {"mean_ic": 0.01, "threshold": 0.03},
                }
            ),
            encoding="utf-8",
        )
        fake_reg = MagicMock()
        fake_reg.register = MagicMock(
            return_value={"status": "rejected", "reason": "IC gate failed"}
        )
        monkeypatch.chdir(tmp_path)
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=fake_reg):
            result = runner.invoke(app, ["ai", "register", "--model-id", "model-abc"])
        assert result.exit_code == 0
        assert "status=rejected" in result.output

    def test_ai_register_ic_unparseable(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1425-1427: IC metrics unparseable → fail-closed NO-GO."""
        report_dir = tmp_path / "data" / "ai_reports"
        report_dir.mkdir(parents=True)
        (report_dir / "model-abc.json").write_text(
            json.dumps(
                {
                    "model_id": "model-abc",
                    "model_cls": "X",
                    "features_hash": "abc",
                    "decision": "GO",
                    "ic_metrics": {"mean_ic": "not-a-number", "threshold": 0.03},
                }
            ),
            encoding="utf-8",
        )
        fake_reg = MagicMock()
        fake_reg.register = MagicMock(
            return_value={"status": "rejected", "reason": "IC metrics unparseable"}
        )
        monkeypatch.chdir(tmp_path)
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=fake_reg):
            result = runner.invoke(app, ["ai", "register", "--model-id", "model-abc"])
        assert result.exit_code == 0
        assert "status=rejected" in result.output

    def test_ai_register_report_fallback(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1402: report not in ai_reports → registry-dir fallback."""
        reg_dir = tmp_path / "registry"
        reg_dir.mkdir()
        (reg_dir / "model-abc.json").write_text(
            json.dumps(
                {
                    "model_id": "model-abc",
                    "model_cls": "X",
                    "features_hash": "abc",
                    "decision": "GO",
                    "validation": {"decision": "GO"},
                }
            ),
            encoding="utf-8",
        )
        fake_reg = MagicMock()
        fake_reg.register = MagicMock(return_value={"status": "paper", "reason": "ok"})
        monkeypatch.chdir(tmp_path)
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=fake_reg):
            result = runner.invoke(
                app,
                [
                    "ai",
                    "register",
                    "--model-id",
                    "model-abc",
                    "--registry-dir",
                    str(reg_dir),
                ],
            )
        assert result.exit_code == 0
        assert "status=paper" in result.output

    def test_ai_validation_bypass_empty(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.ai_validation_bypass.run_ai_validation_bypass",
                return_value=SimpleNamespace(),
            ),
        ):
            result = runner.invoke(app, ["ai", "bypass", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No data" in result.output
