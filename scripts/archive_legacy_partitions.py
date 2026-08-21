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

PARQUET_DIR = Path("data/parquet")
#: Outside ``parquet_dir`` so list_symbols()/web overview never see it.
ARCHIVE_ROOT = Path("data/parquet_archive")

#: Explicit mapping — no heuristic inference. Keys are legacy directory names.
#: ``BTC-USDT-SWAP`` is intentionally absent: it is a perpetual dataset with a
# %% legitimate dash name, not a naming accident (open question O2).
LEGACY_TARGETS: tuple[str, ...] = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT")

META_DIRS = ("meta_funding_rate", "meta_open_interest")


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
                src = PARQUET_DIR / meta / target
                if src.is_dir():
                    entry["moves"].append(str(src))  # type: ignore[union-attr]
            plan.append(entry)

        # Pure-OKX meta history: relabel in place instead of archiving.
        if relabel_meta_okx:
            for meta in META_DIRS:
                src = PARQUET_DIR / meta / "BTC_USDT"
                dst = PARQUET_DIR / meta / "BTC_USDT-OKX"
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

    print(f"== Legacy partition archive plan ({stamp}) {'APPLY' if args.apply else 'DRY-RUN'} ==")
    manifest: dict[str, object] = {"stamp": stamp, "moves": [], "relabels": []}

    for entry in plan:
        replacement = entry["replacement"]
        if not replacement:
            problems.append(
                f"{entry['legacy']}: no suffixed replacement partition found — run the "
                "Binance/OKX re-download first (order iron rule: rerun -> verify -> switch -> archive)."
            )
            continue
        dest_dir = ARCHIVE_ROOT / stamp
        for src_str in entry["moves"]:  # type: ignore[union-attr]
            src = Path(str(src_str))
            dst = dest_dir / src.relative_to(PARQUET_DIR)
            if dst.exists():
                problems.append(f"{src}: destination {dst} already exists.")
                continue
            print(f"  move {src} -> {dst}   (replaced by {replacement})")
            manifest["moves"].append({"src": str(src), "dst": str(dst)})  # type: ignore[union-attr]
            if args.apply:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        for relabel in entry.get("relabel", []):  # type: ignore[union-attr]
            src, dst = Path(relabel[0]), Path(relabel[1])
            print(f"  relabel {src} -> {dst}")
            manifest["relabels"].append({"src": str(src), "dst": str(dst)})  # type: ignore[union-attr]
            if args.apply:
                src.rename(dst)

    if problems:
        print("\nBLOCKED — resolve before applying:")
        for p in problems:
            print(f"  !! {p}")
        return 1

    if args.apply:
        manifest_path = ARCHIVE_ROOT / f"manifest_{stamp}.json"
        ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Rollback = move each manifest entry back (nothing was deleted).
        print(f"\nApplied. Manifest (rollback reference): {manifest_path}")
    else:
        print("\nDry-run only. Re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
