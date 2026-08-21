"""Archive legacy bare (mixed-source) parquet partitions — P4 migration tool.

Three-model consensus (P4, 2026-08-21):
- Archive destination MUST live outside ``parquet_dir`` (``list_symbols``
  enumerates directories at the root; an in-root ``__archive`` dir would leak
  into the web overview as a fake symbol).
- Dry-run by default; ``--apply`` performs the moves. Nothing is ever deleted.
- Safety gates (all must pass per target): the replacement suffixed partition
  exists on disk, and the destination does not already exist.
- The legacy meta partitions (``meta_funding_rate/BTC_USDT`` etc.) are pure
  OKX data (only OKX exposes funding/OI CLIs) and OKX only serves ~90 days of
  funding history — that data is NOT re-downloadable. ``--relabel-meta-okx``
  renames them in place to ``BTC_USDT-OKX`` so the long history survives the
  migration with a truthful label instead of being archived away.

Usage:
    python scripts/archive_legacy_partitions.py            # dry-run plan
    python scripts/archive_legacy_partitions.py --apply    # perform moves
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.data.store import DataStore  # noqa: E402 — after REPO_ROOT setup

PARQUET_DIR = REPO_ROOT / "data" / "parquet"
#: Outside ``parquet_dir`` so list_symbols()/web overview never see it.
ARCHIVE_ROOT = REPO_ROOT / "data" / "parquet_archive"

#: Explicit mapping — no heuristic inference. Keys are legacy directory names.
#: ``BTC-USDT-SWAP`` is intentionally absent: it is a perpetual dataset with a
# %% legitimate dash name, not a naming accident (open question O2).
LEGACY_TARGETS: tuple[str, ...] = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT")

META_DIRS = ("meta_funding_rate", "meta_open_interest")

#: The only legacy dir with relabel-able (pure-OKX, non-redownloadable) meta
#: history today. Kept explicit — extend deliberately if others appear.
RELABEL_TARGET = "BTC_USDT"


def _replacement_ready(store: DataStore, legacy_dir: str) -> str | None:
    """Return the suffixed partition name replacing ``legacy_dir``, if any."""
    base_symbol = legacy_dir.replace("_", "/")
    for suffix in ("-BINANCE", "-OKX"):
        candidate = f"{base_symbol}{suffix}"
        if store.get_date_range(candidate) is not None:
            return candidate
    return None


def build_plan(*, relabel_meta_okx: bool) -> list[dict[str, object]]:
    store = DataStore(str(PARQUET_DIR), ":memory:")
    plan: list[dict[str, object]] = []
    try:
        for target in LEGACY_TARGETS:
            if not (PARQUET_DIR / target).is_dir():
                continue
            entry: dict[str, object] = {
                "legacy": target,
                "replacement": _replacement_ready(store, target),
                "moves": [str(PARQUET_DIR / target)],
            }
            for meta in META_DIRS:
                # F1 fix: when relabel owns this meta path it must NOT also be
                # archived — a path may appear in at most one operation list.
                if relabel_meta_okx and target == RELABEL_TARGET:
                    continue
                src = PARQUET_DIR / meta / target
                if src.is_dir():
                    entry["moves"].append(str(src))  # type: ignore[union-attr]
            plan.append(entry)

        # Pure-OKX meta history: relabel in place instead of archiving.
        if relabel_meta_okx:
            for meta in META_DIRS:
                src = PARQUET_DIR / meta / RELABEL_TARGET
                dst = PARQUET_DIR / meta / f"{RELABEL_TARGET}-OKX"
                if src.is_dir() and not dst.exists():
                    plan.append(
                        {
                            "legacy": f"{meta}/BTC_USDT",
                            "replacement": str(dst),
                            "moves": [],
                            "relabel": [[str(src), str(dst)]],
                        }
                    )
    finally:
        store.close()
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Perform the moves (default: dry-run)")
    parser.add_argument(
        "--relabel-meta-okx",
        action="store_true",
        help="Also rename meta_funding_rate|meta_open_interest/BTC_USDT -> BTC_USDT-OKX "
        "(pure-OKX, non-redownloadable history keeps a truthful label)",
    )
    args = parser.parse_args()

    plan = build_plan(relabel_meta_okx=args.relabel_meta_okx)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    problems: list[str] = []
    moves: list[dict[str, str]] = []
    relabels: list[dict[str, str]] = []

    print(f"== Legacy partition archive plan ({stamp}) {'APPLY' if args.apply else 'DRY-RUN'} ==")

    # ---- Phase 1: full pre-check, no mutations ----------------------------
    # F3 fix: validate EVERYTHING first; a single blocked entry must not
    # leave earlier entries half-applied with no rollback manifest.
    dest_dir = ARCHIVE_ROOT / stamp
    for entry in plan:
        replacement = entry["replacement"]
        if not replacement:
            problems.append(
                f"{entry['legacy']}: no suffixed replacement partition found — run the "
                "Binance/OKX re-download first (order iron rule: rerun -> verify -> switch -> archive)."
            )
            continue
        for src_str in entry["moves"]:  # type: ignore[union-attr]
            src = Path(str(src_str))
            dst = dest_dir / src.relative_to(PARQUET_DIR)
            if not src.is_dir():
                problems.append(f"{src}: source missing (already moved?)")
                continue
            if dst.exists():
                problems.append(f"{src}: destination {dst} already exists.")
                continue
            moves.append({"src": str(src), "dst": str(dst)})
        for relabel in entry.get("relabel", []):  # type: ignore[union-attr]
            src, dst = Path(relabel[0]), Path(relabel[1])
            if not src.is_dir():
                problems.append(f"{src}: relabel source missing (already renamed?)")
                continue
            if dst.exists():
                problems.append(f"{src}: relabel destination {dst} already exists.")
                continue
            relabels.append({"src": str(src), "dst": str(dst)})

    if problems:
        print("\nBLOCKED — nothing was moved. Resolve before applying:")
        for p in problems:
            print(f"  !! {p}")
        return 1

    for m in moves:
        print(f"  move {m['src']} -> {m['dst']}")
    for r in relabels:
        print(f"  relabel {r['src']} -> {r['dst']}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to execute.")
        return 0

    # ---- Phase 2: write-ahead manifest, then execute ----------------------
    # The plan is persisted BEFORE any filesystem change so a mid-run crash
    # still leaves a complete rollback reference.
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = ARCHIVE_ROOT / f"manifest_{stamp}.json"
    manifest_path.write_text(
        json.dumps(
            {"stamp": stamp, "status": "planned", "moves": moves, "relabels": relabels}, indent=2
        ),
        encoding="utf-8",
    )
    for m in moves:
        Path(m["dst"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(m["src"], m["dst"])
    for r in relabels:
        Path(r["src"]).rename(r["dst"])
    manifest_path.write_text(
        json.dumps(
            {"stamp": stamp, "status": "applied", "moves": moves, "relabels": relabels}, indent=2
        ),
        encoding="utf-8",
    )
    # Rollback = move each manifest entry back (nothing was deleted).
    print(f"\nApplied. Manifest (rollback reference): {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
