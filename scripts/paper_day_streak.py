#!/usr/bin/env python3
"""Path A paper day-session streak ledger (T023).

Tracks **calendar UTC days** with a successful Path A day-session summary
(``data/paper_sessions/day_session_*.json`` or ``latest.json``).

Rules (honest wall-clock):
  - One credit per UTC date (multiple runs same day do not multi-count).
  - Pass requires ``status`` in ok-ish set AND (when present) deviation not hard-alert.
  - Does **not** fabricate days; 7-day target is wall-clock progress for T023/T024.

    python scripts/paper_day_streak.py status
    python scripts/paper_day_streak.py ingest
    python scripts/paper_day_streak.py ingest --run-day-session
    python scripts/paper_day_streak.py report --min-days 7
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SESSIONS_DIR = REPO_ROOT / "data" / "paper_sessions"
LEDGER_PATH = SESSIONS_DIR / "streak_ledger.json"
DEFAULT_MIN_DAYS = 7

# status values that count as a successful Path A day (preflight/path healthy)
OK_STATUSES = frozenset(
    {
        "ok",
        "baseline_deviation_degraded",  # soft diagnostic only (T017)
    }
)
# hard failures — never credit
BAD_STATUSES = frozenset(
    {
        "preflight_failed",
        "batch_gate_failed",
        "run_failed",
        "baseline_deviation_alert",
    }
)


def _parse_day(iso_or_name: str) -> date | None:
    """Extract UTC calendar date from ISO timestamp or day_session filename."""
    s = iso_or_name.strip()
    # filename: day_session_20260808T141330Z.json
    if "day_session_" in s:
        try:
            token = s.split("day_session_", 1)[1]
            token = token.replace(".json", "")
            # 20260808T141330Z
            if len(token) >= 8 and token[:8].isdigit():
                return date(int(token[:4]), int(token[4:6]), int(token[6:8]))
        except (ValueError, IndexError):
            pass
    try:
        # ISO
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()
    except ValueError:
        return None


def _load_summary(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def summary_is_credit(summary: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason) whether this summary credits a Path A day."""
    status = str(summary.get("status") or "")
    if status in BAD_STATUSES:
        return False, f"status={status}"
    if status not in OK_STATUSES and status != "ok":
        # unknown status: only credit if preflight_rc==0 and path A
        if summary.get("preflight_rc") not in (0, None):
            return False, f"status={status!r} preflight_rc={summary.get('preflight_rc')}"
        if summary.get("path") not in (None, "A", "a"):
            return False, f"path={summary.get('path')!r}"

    deviation = summary.get("deviation")
    if isinstance(deviation, dict):
        if deviation.get("status") == "alert" or deviation.get("health_ok") is False:
            return False, "deviation hard alert / health_ok=false"
    # Prefer explicit path A
    if summary.get("path") not in (None, "A", "a"):
        return False, f"not path A ({summary.get('path')!r})"
    if status in OK_STATUSES or summary.get("preflight_rc") == 0:
        return True, "ok"
    return False, f"status={status!r}"


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    # Late-bind default so tests can monkeypatch LEDGER_PATH after import.
    path = LEDGER_PATH if path is None else path
    if not path.is_file():
        return {
            "kind": "paper_day_streak",
            "task": "T023",
            "version": 1,
            "days": {},
            "updated_at": None,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "kind": "paper_day_streak",
            "task": "T023",
            "version": 1,
            "days": {},
            "updated_at": None,
            "load_error": True,
        }
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("kind", "paper_day_streak")
    raw.setdefault("task", "T023")
    raw.setdefault("days", {})
    if not isinstance(raw["days"], dict):
        raw["days"] = {}
    return raw


def save_ledger(ledger: dict[str, Any], path: Path | None = None) -> Path:
    path = LEDGER_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def collect_session_files(sessions_dir: Path | None = None) -> list[Path]:
    # Late-bind default so tests can monkeypatch SESSIONS_DIR after import.
    sessions_dir = SESSIONS_DIR if sessions_dir is None else sessions_dir
    if not sessions_dir.is_dir():
        return []
    files = list(sessions_dir.glob("day_session_*.json"))
    latest = sessions_dir / "latest.json"
    if latest.is_file():
        files.append(latest)
    return files


def ingest_files(
    ledger: dict[str, Any],
    files: list[Path] | None = None,
) -> dict[str, Any]:
    """Scan day-session JSONs and merge credited UTC days into ledger."""
    files = files if files is not None else collect_session_files()
    days: dict[str, Any] = dict(ledger.get("days") or {})
    scanned = 0
    credited_now: list[str] = []
    rejected: list[dict[str, str]] = []

    for path in files:
        summary = _load_summary(path)
        if not summary:
            continue
        scanned += 1
        day = _parse_day(str(summary.get("started_at") or path.name))
        if day is None:
            rejected.append({"file": path.name, "reason": "no_date"})
            continue
        ok, reason = summary_is_credit(summary)
        key = day.isoformat()
        if not ok:
            rejected.append({"file": path.name, "day": key, "reason": reason})
            continue
        entry = {
            "date": key,
            "status": summary.get("status"),
            "source": str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if path.is_relative_to(REPO_ROOT)
            else str(path),
            "preflight_rc": summary.get("preflight_rc"),
            "has_deviation": isinstance(summary.get("deviation"), dict),
            "has_baseline_snapshot": isinstance(summary.get("baseline_snapshot"), dict),
            "ingested_at": datetime.now(UTC).isoformat(),
        }
        # Keep first credit of the day; refresh metadata if re-ingested
        days[key] = entry
        credited_now.append(key)

    ledger["days"] = dict(sorted(days.items()))
    ledger["last_ingest"] = {
        "scanned_files": scanned,
        "credited_keys": sorted(set(credited_now)),
        "rejected": rejected[:20],
        "at": datetime.now(UTC).isoformat(),
    }
    return ledger


def streak_stats(ledger: dict[str, Any], *, min_days: int = DEFAULT_MIN_DAYS) -> dict[str, Any]:
    days_map: dict[str, Any] = ledger.get("days") or {}
    credited = sorted(days_map.keys())
    credited_dates = [date.fromisoformat(d) for d in credited]

    # consecutive streak ending at the most recent credited day (or today if credited)
    today = datetime.now(UTC).date()
    consecutive = 0
    cursor = today
    credited_set = set(credited_dates)
    # If today not credited, streak ends at last credited day
    if today not in credited_set and credited_dates:
        cursor = credited_dates[-1]
    while cursor in credited_set:
        consecutive += 1
        cursor = cursor - timedelta(days=1)

    # gaps in last min_days window
    window_start = today - timedelta(days=min_days - 1)
    window_days = [window_start + timedelta(days=i) for i in range(min_days)]
    present = [d.isoformat() for d in window_days if d in credited_set]
    missing = [d.isoformat() for d in window_days if d not in credited_set]

    len(credited_dates) >= min_days and consecutive >= min_days
    # T023 also accepts "≥ min_days distinct UTC days" even if not consecutive,
    # but roadmap says continuous — report both.
    met_distinct = len(credited_dates) >= min_days
    met_consecutive = consecutive >= min_days

    return {
        "credited_dates": credited,
        "n_credited": len(credited_dates),
        "consecutive_ending_recent": consecutive,
        "min_days_target": min_days,
        "window_present": present,
        "window_missing": missing,
        "target_met_consecutive": met_consecutive,
        "target_met_distinct": met_distinct,
        "target_met": met_consecutive,  # strict T023 continuous
        "today": today.isoformat(),
        "note": (
            "target_met requires consecutive UTC days ≥ min_days ending at "
            "today or last credited day; distinct-only is reported separately"
        ),
    }


def run_day_session(*, alert: bool = True) -> int:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "paper_day_session.py")]
    if alert:
        cmd.append("--alert-on-fail")
    print("[streak]", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode


def build_report(ledger: dict[str, Any], *, min_days: int = DEFAULT_MIN_DAYS) -> dict[str, Any]:
    stats = streak_stats(ledger, min_days=min_days)
    return {
        "kind": "paper_day_streak_report",
        "task": "T023",
        "generated_at": datetime.now(UTC).isoformat(),
        "ledger_path": str(LEDGER_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "stats": stats,
        "next_actions": (
            []
            if stats["target_met"]
            else [
                f"Run Path A for missing days: {stats['window_missing'][:5]}",
                "python scripts/paper_day_session.py --alert-on-fail",
                "python scripts/paper_day_streak.py ingest",
                "After ≥7 consecutive UTC days: T024 paper_evidence export",
            ]
        ),
        "path_note": "Path A day-session only; not comparable to Path B gate.json",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show streak stats from ledger")
    p_status.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)

    p_ingest = sub.add_parser("ingest", help="Scan paper_sessions into ledger")
    p_ingest.add_argument(
        "--run-day-session",
        action="store_true",
        help="Run paper_day_session.py --alert-on-fail before ingest",
    )
    p_ingest.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)

    p_report = sub.add_parser("report", help="Write streak report JSON")
    p_report.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)
    p_report.add_argument(
        "--out",
        default="data/paper_sessions/streak_report.json",
    )

    args = ap.parse_args()
    min_days = int(getattr(args, "min_days", DEFAULT_MIN_DAYS))

    if args.cmd == "status":
        ledger = load_ledger()
        # refresh from files without requiring explicit ingest
        ledger = ingest_files(ledger)
        save_ledger(ledger)
        stats = streak_stats(ledger, min_days=min_days)
        print(
            f"[streak] credited={stats['n_credited']} "
            f"consecutive={stats['consecutive_ending_recent']} "
            f"target_met={stats['target_met']} "
            f"(min_days={min_days})"
        )
        print(f"  dates: {stats['credited_dates']}")
        if stats["window_missing"]:
            print(f"  missing in {min_days}d window: {stats['window_missing']}")
        return 0 if stats["n_credited"] >= 0 else 1

    if args.cmd == "ingest":
        if args.run_day_session:
            rc = run_day_session(alert=True)
            if rc != 0:
                print(f"[streak] day-session rc={rc} — still ingesting artifacts", flush=True)
        ledger = load_ledger()
        ledger = ingest_files(ledger)
        save_ledger(ledger)
        stats = streak_stats(ledger, min_days=min_days)
        print(
            f"[streak] ingest done credited={stats['n_credited']} "
            f"consecutive={stats['consecutive_ending_recent']} "
            f"target_met={stats['target_met']}"
        )
        print(f"  ledger → {LEDGER_PATH}")
        return 0

    if args.cmd == "report":
        ledger = load_ledger()
        ledger = ingest_files(ledger)
        save_ledger(ledger)
        report = build_report(ledger, min_days=min_days)
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[streak] report → {out}")
        print(
            f"  consecutive={report['stats']['consecutive_ending_recent']} "
            f"target_met={report['stats']['target_met']}"
        )
        return 0 if report["stats"]["target_met"] else 2  # 2 = in progress

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
