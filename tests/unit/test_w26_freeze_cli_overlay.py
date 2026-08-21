"""W26 tests: B4 freeze template, CLI assert-elliott/freeze-b4, trades overlay."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner


class TestW26aFreeze:
    def test_template_exists_and_keep_b0(self) -> None:
        root = Path(__file__).resolve().parents[2]
        p = root / "docs" / "research" / "baseline4-adjudication-freeze-template.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["baseline"] == "B4"
        assert data["upgrade"] is False
        assert data["keep_baseline0"] is True
        assert data["b4_params"]["entry_threshold"] == 0.0004
        assert data["b3_reference"]["entry_threshold"] == 0.001

    def test_freeze_script_writes_frozen(self, tmp_path: Path) -> None:
        import scripts.freeze_baseline4_adjudication as freeze_mod
        import scripts.run_baseline4_challenger as b4

        out = tmp_path / "baseline4" / "w26"
        assert b4.main(["--dry-run", "--out-dir", str(out)]) == 0
        rc = freeze_mod.main(["--run-dir", str(out)])
        assert rc == 0
        frozen = json.loads((out / "adjudication_frozen.json").read_text(encoding="utf-8"))
        assert frozen["status"] == "FROZEN"
        assert frozen["upgrade"] is False
        assert frozen["keep_baseline0"] is True
        assert frozen["verdict"] in ("KEEP_BASELINE_0", "DRAFT", "KEEP_B0") or (
            "KEEP" in str(frozen["verdict"]).upper()
        )

    def test_freeze_refuses_baseline3(self, tmp_path: Path) -> None:
        import scripts.freeze_baseline4_adjudication as freeze_mod

        bad = tmp_path / "baseline3" / "x"
        bad.mkdir(parents=True)
        (bad / "run_meta.json").write_text("{}", encoding="utf-8")
        rc = freeze_mod.main(["--run-dir", str(bad)])
        assert rc == 2


class TestW26bCli:
    def test_assert_elliott_build(self, tmp_path: Path) -> None:
        from quantflow.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "assert-elliott",
                "--build",
                "--dir",
                str(tmp_path / "pkg"),
                "--n-bars",
                "50",
                "--no-reseat",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "pkg" / "cost_report.json").is_file()

    def test_freeze_b4_cli(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4
        from quantflow.cli.main import app

        out = tmp_path / "baseline4" / "cli"
        assert b4.main(["--dry-run", "--out-dir", str(out)]) == 0
        runner = CliRunner()
        result = runner.invoke(app, ["freeze-b4", "--run-dir", str(out)])
        assert result.exit_code == 0, result.output
        assert (out / "adjudication_frozen.json").is_file()


class TestW26cOverlay:
    def test_trades_multi_overlay_yaml(self) -> None:
        root = Path(__file__).resolve().parents[2]
        p = root / "quantflow" / "config" / "paper_trades_multi_overlay.yaml"
        text = p.read_text(encoding="utf-8")
        assert "trades_poll_enabled: true" in text
        assert "BTC/USDT" in text
        # default AppConfig still off
        from quantflow.common.config import ExecutionConfig

        assert ExecutionConfig().trades_poll_enabled is False
