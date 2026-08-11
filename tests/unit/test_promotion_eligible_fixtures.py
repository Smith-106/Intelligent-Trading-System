"""Wave C1: research JSON fixtures must keep promotion_eligible fail-closed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "research_promotion"


def _assert_no_true_promotion(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        if "promotion_eligible" in node:
            assert node["promotion_eligible"] is False, (
                f"{path}.promotion_eligible must be false, got {node['promotion_eligible']!r}"
            )
        for k, v in node.items():
            _assert_no_true_promotion(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_true_promotion(v, f"{path}[{i}]")


@pytest.mark.parametrize(
    "name",
    [
        "dual_path_sample.json",
        "path_b_oos_sample.json",
    ],
)
def test_fixture_promotion_eligible_false(name: str) -> None:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    _assert_no_true_promotion(data)
    # Top-level or nested path views
    if "promotion_eligible" in data:
        assert data["promotion_eligible"] is False
    paths = data.get("paths") or {}
    for key, view in paths.items():
        if isinstance(view, dict) and "promotion_eligible" in view:
            assert view["promotion_eligible"] is False, key


def test_runtime_perf_verify_artifacts_if_present() -> None:
    """Optional: local perf_verify outputs must also stay fail-closed."""
    base = REPO / "data" / "paper_replay" / "perf_verify"
    for name in ("dual_path.json", "path_b_oos.json"):
        p = base / name
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        _assert_no_true_promotion(data)


def test_fixtures_reject_combined_score_key() -> None:
    for path in FIXTURES.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        path_name = path.name

        def _walk(node: Any, *, name: str = path_name) -> None:
            if isinstance(node, dict):
                assert "combined_score" not in node, f"{name} has combined_score key"
                for v in node.values():
                    _walk(v, name=name)
            elif isinstance(node, list):
                for v in node:
                    _walk(v, name=name)

        _walk(data)
