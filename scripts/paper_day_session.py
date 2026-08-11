#!/usr/bin/env python3
"""Single-command Baseline-0 paper day-session (P0 T004).

Orchestrates:
  1) preflight (data quality + overlay contract)
  2) optional short paper-mode dry harness / status note
  3) session summary artifact under data/paper_sessions/
  4) optional alert hook (Telegram/LINE) when summary fails thresholds

This does **not** start an unbounded live loop by default. Use
``--start-run`` to hand off to ``quantflow run --mode paper ...`` after
preflight OK (foreground; Ctrl-C to stop).

Path A (daily paper, no nested gate) is the default — see
docs/research/baseline0-paper-run-checklist.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OVERLAY = "quantflow/config/paper_baseline0_overlay.yaml"
ORDERBOOK_OVERLAY = "quantflow/config/paper_day_orderbook_overlay.yaml"


def _baseline_symbols_csv() -> str:
    try:
        from quantflow.strategy.research.universe_config import baseline_symbols_csv

        return baseline_symbols_csv(repo_root=REPO_ROOT)
    except Exception:  # noqa: BLE001
        return "BTC/USDT,ETH/USDT,SOL/USDT"


SYMBOLS = _baseline_symbols_csv()
OUT_DIR = REPO_ROOT / "data" / "paper_sessions"


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    print("[day-session]", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=check,
        text=True,
        capture_output=False,
    )


def _preflight() -> int:
    return _run(
        [sys.executable, str(REPO_ROOT / "scripts" / "preflight_baseline0_paper.py")]
    ).returncode


def _write_summary(payload: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT_DIR / f"day_session_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # Also refresh "latest" pointer for dashboards / alert hooks.
    latest = OUT_DIR / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _maybe_alert(summary: dict[str, Any], *, enable: bool) -> None:
    if not enable:
        return
    # Alert on non-ok day status OR explicit deviation.should_alert (T017).
    deviation = summary.get("deviation") if isinstance(summary.get("deviation"), dict) else {}
    should = summary.get("status") != "ok" or bool(deviation.get("should_alert"))
    if not should:
        return
    msg = (
        f"[QuantFlow day-session] status={summary.get('status')} "
        f"preflight_rc={summary.get('preflight_rc')} "
        f"note={summary.get('note', '')}"
    )
    if deviation:
        try:
            from quantflow.strategy.research.day_deviation import format_alert_message

            msg = msg + "\n" + format_alert_message(deviation)
        except Exception:  # noqa: BLE001
            msg = msg + f"\n  deviation_status={deviation.get('status')}"
    print(f"[day-session] ALERT: {msg}", flush=True)
    # Best-effort: reuse monitoring alert channel if configured; never raise.
    try:
        from quantflow.monitoring.alerts import send_alert  # type: ignore

        send_alert(msg)  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001 — alert path must not break day session
        print(f"[day-session] alert hook skipped: {exc}", flush=True)


def _attach_baseline_deviation(
    summary: dict[str, Any],
    *,
    day_metrics: dict[str, Any] | None = None,
    day_metrics_path: str | None = None,
) -> dict[str, Any]:
    """T017: embed Baseline snapshot + deviation block into day-session summary."""
    from quantflow.strategy.research.day_deviation import (
        evaluate_day_deviation,
        load_baseline_snapshot,
    )

    metrics = dict(day_metrics) if day_metrics else None
    if metrics is None and day_metrics_path:
        p = Path(day_metrics_path)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # Accept either flat metrics or nested report.
                    if any(k in raw for k in ("return_pct", "max_drawdown_pct")):
                        metrics = raw
                    elif isinstance(raw.get("metrics"), dict):
                        metrics = raw["metrics"]
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[day-session] day metrics load failed: {exc}", flush=True)

    snap = load_baseline_snapshot(repo_root=REPO_ROOT)
    report = evaluate_day_deviation(baseline=snap, day_metrics=metrics, repo_root=REPO_ROOT)
    summary["baseline_snapshot"] = {
        "id": snap.get("baseline_id"),
        "decision": snap.get("decision"),
        "gate_present": snap.get("gate_present"),
        "window": snap.get("window"),
        "metrics": snap.get("metrics"),
        "path_note": snap.get("path_note"),
    }
    summary["deviation"] = report
    # Elevate status only on hard baseline health failures (not diagnostic PnL).
    if report.get("status") == "alert" and summary.get("status") == "ok":
        summary["status"] = "baseline_deviation_alert"
        summary["note"] = "; ".join(report.get("issues") or ["baseline health alert"])
    elif report.get("status") == "degraded" and summary.get("status") == "ok":
        summary["status"] = "baseline_deviation_degraded"
        # Keep note soft — Path A≠B diagnostic warnings.
        summary["note"] = (
            summary.get("note") or "preflight passed"
        ) + "; deviation degraded (diagnostic)"
    print(
        f"[day-session] deviation status={report.get('status')} "
        f"health_ok={report.get('health_ok')} alerts={len(report.get('alerts') or [])}",
        flush=True,
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--start-run",
        action="store_true",
        help="After preflight OK, exec quantflow run --mode paper (blocking)",
    )
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--interval", type=int, default=60, help="Bar poll interval seconds")
    ap.add_argument("--strategy", default="trend_following")
    ap.add_argument("--config", default=OVERLAY)
    ap.add_argument("--alert-on-fail", action="store_true", help="Fire alert hook if not OK")
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Dangerous: skip preflight (not recommended)",
    )
    ap.add_argument(
        "--batch-gate",
        action="store_true",
        help="T015: after preflight OK, run batch_gate_pipeline (fast cost/funding)",
    )
    ap.add_argument(
        "--batch-strategies",
        default="trend_following",
        help="Comma list for --batch-gate (default: trend_following)",
    )
    ap.add_argument(
        "--skip-deviation",
        action="store_true",
        help="T017: skip Baseline deviation block in summary",
    )
    ap.add_argument(
        "--day-metrics",
        default="",
        help="Optional Path A metrics JSON for diagnostic PnL band vs Baseline full RP",
    )
    ap.add_argument(
        "--orderbook-fill",
        action="store_true",
        help=(
            "Wave B3: use paper_day_orderbook_overlay (orderbook_fill + bbo_poll). "
            "Default OFF. Requires --config only if you need a custom path; "
            "this flag overrides --config to the orderbook overlay."
        ),
    )
    args = ap.parse_args()

    # B3: optional orderbook-fill path — never the silent default.
    if args.orderbook_fill:
        if args.config == OVERLAY:
            args.config = ORDERBOOK_OVERLAY
        print(
            f"[day-session] orderbook-fill ON → config={args.config} "
            "(bbo_poll + orderbook_fill; still paper-only)",
            flush=True,
        )

    started = datetime.now(UTC).isoformat()
    t0 = time.time()

    preflight_rc = 0
    if not args.skip_preflight:
        preflight_rc = _preflight()
    else:
        print("[day-session] WARN: --skip-preflight set", flush=True)

    status = "ok" if preflight_rc == 0 else "preflight_failed"
    note = "preflight passed" if preflight_rc == 0 else "fix preflight before paper"

    summary: dict[str, Any] = {
        "kind": "paper_day_session",
        "path": "A",  # daily paper — no nested gate
        "started_at": started,
        "preflight_rc": preflight_rc,
        "status": status,
        "note": note,
        "contract": {
            "symbols": SYMBOLS,
            "timeframe": "1h",
            "strategy": args.strategy,
            "config": args.config,
            "mode": "paper",
            "fee_slip": "0.001/0.001 via overlay",
            "orderbook_fill": bool(args.orderbook_fill),
            "bbo_poll_requested": bool(args.orderbook_fill),
        },
        "commands": {
            "preflight": "python scripts/preflight_baseline0_paper.py",
            "run": (
                f"quantflow run --mode paper --strategy {args.strategy} "
                f"--symbols {SYMBOLS} --timeframe 1h --interval {args.interval} "
                f"--capital {args.capital:g} --config {args.config}"
            ),
            "research_path_b": "python scripts/run_baseline0.py",
            "batch_gate": (
                f"python scripts/batch_gate_pipeline.py --strategies {args.batch_strategies}"
            ),
        },
    }

    if not args.skip_deviation:
        summary = _attach_baseline_deviation(
            summary,
            day_metrics_path=args.day_metrics or None,
        )
        summary["commands"]["deviation"] = (
            'python -c "from quantflow.strategy.research.day_deviation import '
            'evaluate_day_deviation; print(evaluate_day_deviation())"'
        )

    summary_path = _write_summary(summary)
    print(f"[day-session] summary → {summary_path}", flush=True)
    _maybe_alert(summary, enable=args.alert_on_fail)

    if preflight_rc != 0:
        print("[day-session] STOP: preflight failed", flush=True)
        return preflight_rc

    if args.batch_gate:
        batch_out = REPO_ROOT / "data" / "paper_sessions" / "batch_gate_latest.json"
        batch_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "batch_gate_pipeline.py"),
            "--strategies",
            args.batch_strategies,
            "--after-day-session",
            "--out",
            str(batch_out.relative_to(REPO_ROOT)).replace("\\", "/"),
            "--allow-partial",
        ]
        batch_rc = _run(batch_cmd).returncode
        summary["batch_gate_rc"] = batch_rc
        summary["batch_gate_out"] = str(batch_out.relative_to(REPO_ROOT)).replace("\\", "/")
        if batch_rc != 0:
            summary["status"] = "batch_gate_failed"
            summary["note"] = "batch_gate_pipeline returned non-zero"
        summary_path = _write_summary(summary)
        print(f"[day-session] batch-gate rc={batch_rc} → {summary_path}", flush=True)
        _maybe_alert(summary, enable=args.alert_on_fail)

    if args.start_run:
        cmd = [
            sys.executable,
            "-m",
            "quantflow",
            "run",
            "--mode",
            "paper",
            "--strategy",
            args.strategy,
            "--symbols",
            SYMBOLS,
            "--timeframe",
            "1h",
            "--interval",
            str(args.interval),
            "--capital",
            str(args.capital),
            "--config",
            args.config,
        ]
        print("[day-session] starting paper run (Ctrl-C to stop)...", flush=True)
        rc = _run(cmd).returncode
        summary["run_rc"] = rc
        summary["finished_at"] = datetime.now(UTC).isoformat()
        summary["elapsed_s"] = round(time.time() - t0, 1)
        summary["status"] = "ok" if rc == 0 else "run_failed"
        summary_path = _write_summary(summary)
        print(f"[day-session] final summary → {summary_path}", flush=True)
        _maybe_alert(summary, enable=args.alert_on_fail)
        return rc

    print("[day-session] preflight OK — not starting run (pass --start-run to hand off)")
    print(summary["commands"]["run"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
