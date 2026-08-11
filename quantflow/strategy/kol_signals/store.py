"""Append-only JSONL store for KOL signals + consensus snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from quantflow.strategy.kol_signals.models import KolSignal

DEFAULT_DIR = Path("data/kol_signals")


class KolSignalStore:
    def __init__(self, root: str | Path = DEFAULT_DIR) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.signals_path = self.root / "signals.jsonl"
        self.consensus_path = self.root / "consensus.jsonl"

    def append_signal(self, signal: KolSignal) -> None:
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(signal.to_dict(), ensure_ascii=False) + "\n")

    def append_signals(self, signals: Iterable[KolSignal]) -> int:
        n = 0
        with self.signals_path.open("a", encoding="utf-8") as f:
            for s in signals:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
                n += 1
        return n

    def append_consensus(self, reports: list[dict[str, Any]]) -> None:
        if not reports:
            return
        with self.consensus_path.open("a", encoding="utf-8") as f:
            for r in reports:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def load_signals(self, *, limit: int | None = None) -> list[KolSignal]:
        if not self.signals_path.is_file():
            return []
        rows: list[KolSignal] = []
        with self.signals_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(KolSignal.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        if limit is not None and limit >= 0:
            return rows[-limit:]
        return rows

    def dedupe_key(self, platform: str, channel_id: str, message_id: str) -> str:
        return f"{platform}:{channel_id}:{message_id}"

    def known_message_ids(self) -> set[str]:
        known: set[str] = set()
        for s in self.load_signals():
            known.add(self.dedupe_key(s.platform, s.channel_id, s.message_id))
        return known
