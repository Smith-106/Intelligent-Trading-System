"""W27: engineering wave track close — docs + no further W28+ candidates."""

from __future__ import annotations

from pathlib import Path


def test_w27_close_doc_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    p = root / "docs" / "research" / "w27-wave-track-close.md"
    text = p.read_text(encoding="utf-8")
    assert "CLOSED" in text
    assert "W28" in text or "no further" in text.lower()


def test_roadmap_has_no_open_engineering_wave_candidates() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs" / "research" / "option-b-evolution-roadmap.md").read_text(
        encoding="utf-8"
    )
    assert "### W27 — Option B 工程 wave 轨道收口" in text
    # Must not advertise a new open feature-wave backlog
    assert "### W28+" not in text
    assert "### W27+ 候选（未开工）" not in text
    assert "### W26+ 候选（未开工）" not in text
    # W26 and W25 sections marked complete
    assert "**W26a**" in text and "✅" in text
