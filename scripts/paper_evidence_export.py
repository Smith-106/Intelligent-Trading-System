#!/usr/bin/env python3
"""Export paper_evidence + ModelRegistry promote dry-run (T024).

Builds a ``paper_evidence`` JSON from the T023 streak ledger (and optional
fill overrides), then optionally:

  1) registers a throwaway paper model (cost+funding GO stub)
  2) attach_paper_evidence
  3) promote_to_live — expect reject if short sample, pass if floors met

Does **not** touch live trading or production registry dirs by default
(uses ``data/paper_sessions/dry_registry/``).

    python scripts/paper_evidence_export.py export
    python scripts/paper_evidence_export.py dry-run
    python scripts/paper_evidence_export.py dry-run --synthetic-full
    python scripts/paper_evidence_export.py dry-run --fills 25
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SESSIONS_DIR = REPO_ROOT / "data" / "paper_sessions"
LEDGER_PATH = SESSIONS_DIR / "streak_ledger.json"
DEFAULT_EVIDENCE_OUT = SESSIONS_DIR / "paper_evidence_latest.json"
DEFAULT_DRY_REGISTRY = SESSIONS_DIR / "dry_registry"


def _load_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {"days": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"days": {}}
    return raw if isinstance(raw, dict) else {"days": {}}


def evidence_from_streak(
    ledger: dict[str, Any] | None = None,
    *,
    fills: int | None = None,
    orders: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build paper_evidence from credited streak days (T023 ledger)."""
    led = ledger if ledger is not None else _load_ledger()
    days_map = led.get("days") if isinstance(led.get("days"), dict) else {}
    dates = sorted(days_map.keys())
    if not dates:
        started = ended = None
        paper_days = 0.0
    else:
        started = f"{dates[0]}T00:00:00+00:00"
        ended = f"{dates[-1]}T23:59:59+00:00"
        # Inclusive calendar span (matches T016 day measurement spirit)
        d0 = datetime.fromisoformat(dates[0]).date()
        d1 = datetime.fromisoformat(dates[-1]).date()
        paper_days = float((d1 - d0).days + 1)

    # Prefer consecutive ending recent if streak helper available
    consecutive = None
    try:
        import importlib.util

        p = REPO_ROOT / "scripts" / "paper_day_streak.py"
        spec = importlib.util.spec_from_file_location("paper_day_streak", p)
        if spec and spec.loader:
            streak_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(streak_mod)
            st = streak_mod.streak_stats(led, min_days=7)
            consecutive = st.get("consecutive_ending_recent")
            # Session coverage for readiness = consecutive Path A credits
            if consecutive is not None and consecutive > 0:
                paper_days = float(consecutive)
    except Exception:  # noqa: BLE001
        pass

    evidence: dict[str, Any] = {
        "kind": "paper_evidence",
        "task": "T024",
        "source": "paper_day_streak",
        "paper_days": paper_days,
        "credited_dates": dates,
        "n_credited_days": len(dates),
        "consecutive_days": consecutive,
        "started_at": started,
        "ended_at": ended,
        "exported_at": datetime.now(UTC).isoformat(),
        "path_note": "Path A day-session credits only; not Path B gate PnL",
    }
    if fills is not None:
        evidence["fills"] = int(fills)
    else:
        # Explicit null-ish: force measurable field for gate messaging
        evidence["fills"] = int(led.get("fills_hint") or 0)
    if orders is not None:
        evidence["orders"] = int(orders)
    if notes:
        evidence["notes"] = notes
    evidence["meets_default_floors"] = (
        float(evidence["paper_days"]) >= 7.0 and int(evidence.get("fills") or 0) >= 20
    )
    return evidence


def synthetic_full_evidence(*, days: float = 14.0, fills: int = 40) -> dict[str, Any]:
    """Demo-only evidence that passes default T016 floors (not real ops days)."""
    end = datetime.now(UTC)
    start = end - timedelta(days=float(days))
    return {
        "kind": "paper_evidence",
        "task": "T024",
        "source": "synthetic_full_demo",
        "paper_days": float(days),
        "fills": int(fills),
        "orders": int(fills),
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "exported_at": datetime.now(UTC).isoformat(),
        "notes": (
            "SYNTHETIC — for dry-run promote pass path only; "
            "do not treat as real paper sample"
        ),
        "meets_default_floors": True,
    }


def _go_report() -> dict[str, Any]:
    from quantflow.strategy.validation.cost_fidelity import build_funding_tca

    return {
        "decision": "GO",
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
        ],
        "funding_tca": build_funding_tca(mode="assumption"),
    }


def dry_run_promote(
    evidence: dict[str, Any],
    *,
    registry_dir: Path | None = None,
    model_id: str = "dry-t024",
) -> dict[str, Any]:
    """Register → attach → promote in an isolated registry directory."""
    from quantflow.strategy.model_registry import ModelRegistry, ModelRegistryError

    if registry_dir is None:
        registry_dir = DEFAULT_DRY_REGISTRY
    registry_dir.mkdir(parents=True, exist_ok=True)

    # Fresh model id each run to avoid already-registered / rejected sticky state
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mid = f"{model_id}-{stamp}"

    reg = ModelRegistry(registry_dir)
    reg.register(mid, "DryRunStub", "t024", _go_report())
    reg.attach_paper_evidence(mid, evidence)

    result: dict[str, Any] = {
        "model_id": mid,
        "registry_dir": str(registry_dir),
        "evidence": evidence,
        "attach": "ok",
    }
    try:
        entry = reg.promote_to_live(mid)
        result["promote"] = "live"
        result["status"] = entry.get("status")
        result["paper_readiness"] = entry.get("paper_readiness")
    except ModelRegistryError as exc:
        entry = reg.get(mid) or {}
        result["promote"] = "rejected"
        result["status"] = entry.get("status")
        result["reason"] = str(exc)
        result["entry_reason"] = entry.get("reason")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Write paper_evidence JSON from streak")
    p_exp.add_argument("--out", default=str(DEFAULT_EVIDENCE_OUT))
    p_exp.add_argument("--fills", type=int, default=None)
    p_exp.add_argument("--orders", type=int, default=None)

    p_dry = sub.add_parser("dry-run", help="export + attach + promote in dry registry")
    p_dry.add_argument("--out", default=str(DEFAULT_EVIDENCE_OUT))
    p_dry.add_argument("--fills", type=int, default=None)
    p_dry.add_argument(
        "--synthetic-full",
        action="store_true",
        help="Use synthetic 14d/40 fills evidence (demo pass path only)",
    )
    p_dry.add_argument(
        "--registry-dir",
        default=str(DEFAULT_DRY_REGISTRY),
        help="Isolated registry directory (default under paper_sessions)",
    )
    p_dry.add_argument("--json", action="store_true")

    args = ap.parse_args()

    if args.cmd == "export":
        ev = evidence_from_streak(_load_ledger(), fills=args.fills, orders=args.orders)
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ev, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[evidence] wrote {out}")
        print(
            f"  paper_days={ev.get('paper_days')} fills={ev.get('fills')} "
            f"meets_floors={ev.get('meets_default_floors')}"
        )
        return 0

    if args.cmd == "dry-run":
        if args.synthetic_full:
            ev = synthetic_full_evidence()
        else:
            ev = evidence_from_streak(_load_ledger(), fills=args.fills)
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ev, indent=2, ensure_ascii=False), encoding="utf-8")

        reg_dir = Path(args.registry_dir)
        if not reg_dir.is_absolute():
            reg_dir = REPO_ROOT / reg_dir
        result = dry_run_promote(ev, registry_dir=reg_dir)
        report_path = SESSIONS_DIR / "promote_dry_run_latest.json"
        report_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"[evidence] {out}")
            print(
                f"[dry-run] promote={result['promote']} status={result.get('status')} "
                f"model={result['model_id']}"
            )
            if result.get("reason"):
                print(f"  reason: {result['reason']}")
            print(f"  report → {report_path}")
            print(
                "  note: default floors min_paper_days=7 min_fills=20; "
                "short real streak should reject; --synthetic-full demos pass"
            )
        # Exit 0 for both reject and live — dry-run is informational.
        # Use exit 3 when rejected so CI can distinguish if desired.
        return 0 if result["promote"] == "live" else 3

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
