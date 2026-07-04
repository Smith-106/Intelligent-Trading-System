"""Persistence helpers for QuantFlow Station histories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StationHistoryStore:
    """Persist recent station activity for frontend replay and review."""

    base_dir: Path = field(default_factory=lambda: Path("data") / "station_history")

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)

    def append_research_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result", {})
        request = payload.get("request", {})
        record = {
            "record_id": f"research-{uuid4().hex[:12]}",
            "kind": "research",
            "created_at": _utc_now(),
            "strategy": request.get("strategy"),
            "symbol": request.get("symbol"),
            "request": request,
            "data_source": payload.get("data_source"),
            "summary": {
                "total_return": result.get("total_return"),
                "sharpe_ratio": result.get("sharpe_ratio"),
                "max_drawdown": result.get("max_drawdown"),
                "num_trades": result.get("num_trades"),
            },
            "payload": payload,
        }
        self._append("research_runs", record)
        return record

    def list_research_runs(self, limit: int = 12) -> list[dict[str, Any]]:
        return self._list("research_runs", limit=limit)

    def append_validation_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result", {})
        request = payload.get("request", {})
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            summary = {
                "method": payload.get("method"),
                "decision": result.get("decision"),
                "reason": result.get("reason"),
                "entries": payload.get("signals", {}).get("entries"),
                "exits": payload.get("signals", {}).get("exits"),
                "bars": payload.get("signals", {}).get("bars"),
            }
        record = {
            "record_id": f"validation-{uuid4().hex[:12]}",
            "kind": "validation",
            "created_at": _utc_now(),
            "strategy": request.get("strategy"),
            "symbol": request.get("symbol"),
            "request": request,
            "data_source": payload.get("data_source"),
            "summary": summary,
            "payload": payload,
        }
        self._append("validation_runs", record)
        return record

    def list_validation_runs(self, limit: int = 12) -> list[dict[str, Any]]:
        return self._list("validation_runs", limit=limit)

    def append_session_event(self, event: dict[str, Any]) -> dict[str, Any]:
        record = dict(event)
        record.setdefault("record_id", f"event-{uuid4().hex[:12]}")
        record.setdefault("created_at", _utc_now())
        self._append("session_events", record)
        return record

    def list_session_events(
        self,
        *,
        limit: int = 40,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._list(
            "session_events",
            limit=limit,
            filter_key="session_id" if session_id else None,
            filter_value=session_id,
        )

    def append_session_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        record = dict(snapshot)
        record.setdefault("record_id", f"session-{uuid4().hex[:12]}")
        record.setdefault("created_at", _utc_now())
        self._append("session_snapshots", record)
        return record

    def list_session_snapshots(self, limit: int = 12) -> list[dict[str, Any]]:
        return self._list("session_snapshots", limit=limit, dedupe_key="session_id")

    def save_workbench_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record["savedAt"] = str(record.get("savedAt") or _utc_now())
        path = self.base_dir / "workbench_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def load_workbench_state(self) -> dict[str, Any] | None:
        path = self.base_dir / "workbench_state.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _append(self, category: str, record: dict[str, Any]) -> None:
        path = self.base_dir / f"{category}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _list(
        self,
        category: str,
        *,
        limit: int,
        filter_key: str | None = None,
        filter_value: str | None = None,
        dedupe_key: str | None = None,
    ) -> list[dict[str, Any]]:
        path = self.base_dir / f"{category}.jsonl"
        if not path.exists():
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            item = json.loads(line)
            if filter_key and item.get(filter_key) != filter_value:
                continue
            if dedupe_key:
                dedupe_value = str(item.get(dedupe_key, ""))
                if dedupe_value in seen:
                    continue
                seen.add(dedupe_value)
            results.append(item)
            if len(results) >= limit:
                break
        return results
