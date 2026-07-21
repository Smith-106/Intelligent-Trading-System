"""Persistence helpers for QuantFlow Station histories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# Cap each JSONL category file so it does not grow unbounded across a
# long-running station session (events are appended per SIGNAL/ORDER/FILL/RISK).
_MAX_JSONL_BYTES = 8 * 1024 * 1024

# ISS-009 (SEC-018): per-line size cap. A single malformed/huge record (e.g. a
# payload with an embedded megabyte blob) should not be appendable as one line,
# bounding the worst-case memory when _read_tail_lines parses the tail.
_MAX_JSONL_LINE_BYTES = 256 * 1024

# Whitelist of valid category names. _append/_list build the path as
# base_dir / f"{category}.jsonl"; category always comes from code-internal
# callers today, but validating it defends against a future caller passing a
# path-shaped value (e.g. "../x") that would escape base_dir.
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "research_runs",
        "validation_runs",
        "session_events",
        "session_snapshots",
    }
)


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
        # ISS-009: category builds the path; reject anything outside the
        # whitelist so a path-shaped value cannot escape base_dir.
        if category not in _VALID_CATEGORIES:
            raise ValueError(f"unknown history category: {category!r}")
        path = self.base_dir / f"{category}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # ISS-009 (SEC-018): bound per-line size so one oversized record cannot
        # dominate the file or blow memory on the next tail-read. Truncate the
        # record's payload rather than refuse the write — the event still lands
        # (lifecycle/audit continuity) without the megabyte blob.
        if len(line.encode("utf-8")) > _MAX_JSONL_LINE_BYTES:
            line = self._truncate_line(category, record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        # Cap on-disk growth: if the file exceeds the limit, truncate to the
        # most recent _MAX_JSONL_BYTES worth of complete lines so the file
        # does not grow unbounded over a long-running station session.
        try:
            if path.stat().st_size > _MAX_JSONL_BYTES:
                self._rotate(path)
        except OSError:
            pass

    @staticmethod
    def _truncate_line(category: str, record: dict[str, Any]) -> str:
        """Render an oversized record as a capped placeholder line.

        Drops the bulky ``payload``/``request``/``data`` fields (which carry
        the backtest result / chart points that bloat a record past the line
        cap) and keeps the audit-critical keys (record_id, kind, created_at,
        strategy, symbol, summary). The record remains valid JSONL.
        """
        keep_keys = {
            "record_id",
            "kind",
            "created_at",
            "session_id",
            "event_type",
            "title",
            "level",
            "message",
            "strategy",
            "symbol",
            "summary",
            "operator_id",
            "data",
        }
        slim = {k: v for k, v in record.items() if k in keep_keys}
        slim["_truncated"] = True
        slim["_reason"] = f"record exceeded {_MAX_JSONL_LINE_BYTES}B line cap"
        return json.dumps(slim, ensure_ascii=False, default=str) + "\n"

    @staticmethod
    def _rotate(path: Path) -> None:
        """Truncate a JSONL file to its most recent complete tail."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        lines = text.splitlines()
        # Keep as many recent complete lines as fit under the cap.
        kept: list[str] = []
        size = 0
        for line in reversed(lines):
            if not line:
                continue
            if size + len(line) + 1 > _MAX_JSONL_BYTES and kept:
                break
            kept.append(line)
            size += len(line) + 1
        kept.reverse()
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")

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
        # Read only the tail of the file to bound memory on long sessions.
        lines = self._read_tail_lines(path, max_lines=max(limit * 8, 256))
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                # Skip corrupt/partial lines rather than failing the request.
                continue
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

    @staticmethod
    def _read_tail_lines(path: Path, *, max_lines: int) -> list[str]:
        """Return up to ``max_lines`` trailing lines of ``path``.

        Reads the file tail in chunks so a multi-hundred-MB JSONL file does
        not have to be loaded fully into memory on every poll.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return []
        chunk_size = 64 * 1024
        lines: list[str] = []
        pos = size
        with path.open("rb") as handle:
            while pos > 0 and len(lines) < max_lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                handle.seek(pos)
                data = handle.read(read_size).decode("utf-8", errors="replace")
                parts = data.split("\n")
                if lines:
                    # The leading partial of this chunk joins the trailing partial of the previous.
                    parts[0] = parts[0] + lines[0]
                    lines = parts[1:] + lines[1:]
                else:
                    lines = parts
                if pos == 0:
                    break
        # Drop a possible leading empty string from the split.
        if lines and lines[0] == "":
            lines = lines[1:]
        return lines[-max_lines:]
