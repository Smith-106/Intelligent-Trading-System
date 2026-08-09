"""Tests for strategy scaffold + path A/B CLI banner (P1 T005)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantflow.cli.main import app
from quantflow.strategy.scaffold import ScaffoldError, scaffold_strategy, validate_strategy_id


def test_validate_strategy_id():
    assert validate_strategy_id("my_alpha") == "my_alpha"
    with pytest.raises(ScaffoldError):
        validate_strategy_id("Bad-Id")


def test_scaffold_writes_three_files(tmp_path: Path):
    # minimal package layout
    (tmp_path / "quantflow" / "strategy" / "templates").mkdir(parents=True)
    (tmp_path / "quantflow" / "config" / "strategies").mkdir(parents=True)
    (tmp_path / "docs" / "research").mkdir(parents=True)
    result = scaffold_strategy("demo_alpha", repo_root=tmp_path, description="demo")
    assert result.module_path.is_file()
    assert result.yaml_path.is_file()
    assert result.checklist_path.is_file()
    text = result.module_path.read_text(encoding="utf-8")
    assert "class DemoAlphaStrategy" in text
    assert "generate_signals" in text
    assert "Path A" in result.checklist_path.read_text(encoding="utf-8")


def test_scaffold_refuses_overwrite(tmp_path: Path):
    (tmp_path / "quantflow" / "strategy" / "templates").mkdir(parents=True)
    (tmp_path / "quantflow" / "config" / "strategies").mkdir(parents=True)
    (tmp_path / "docs" / "research").mkdir(parents=True)
    scaffold_strategy("demo_alpha", repo_root=tmp_path)
    with pytest.raises(ScaffoldError, match="overwrite"):
        scaffold_strategy("demo_alpha", repo_root=tmp_path)


def test_cli_new_strategy(tmp_path: Path):
    (tmp_path / "quantflow" / "strategy" / "templates").mkdir(parents=True)
    (tmp_path / "quantflow" / "config" / "strategies").mkdir(parents=True)
    (tmp_path / "docs" / "research").mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new-strategy", "cli_alpha", "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "Scaffolded strategy" in result.stdout
    assert (tmp_path / "quantflow" / "strategy" / "templates" / "cli_alpha.py").is_file()
