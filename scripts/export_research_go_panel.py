#!/usr/bin/env python3
"""Thin CLI export of the sealed L6 research GO panel (TASK-002).

Loads the sealed source of truth ``data/paper_replay/perf_verify/
performance_panel.json`` through the fail-soft loader and prints the typed
snapshot as JSON; optionally pushes the ``quantflow_research_go_*``
Prometheus gauges (off hot path — never called from TradingSession.on_bar).

    python scripts/export_research_go_panel.py
    python scripts/export_research_go_panel.py --push-metrics
    python scripts/export_research_go_panel.py --panel path/to/panel.json

Exit codes: 0 = loaded (and gauges pushed if requested); 2 = panel missing /
invalid (fail-soft, explicit JSON payload on stdout, no traceback).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.monitoring.metrics import (  # noqa: E402  (repo-root sys.path)
    update_research_go_panel_metrics,
)
from quantflow.monitoring.research_go_panel import (  # noqa: E402
    DEFAULT_RESEARCH_GO_PANEL_PATH,
    load_research_go_panel,
)

# Windows consoles default to GBK/CP936; the panel path_semantics carry
# non-ASCII glyphs (e.g. U+2194). Reconfigure stdout so the JSON export
# never crashes on UnicodeEncodeError in a legacy console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_PANEL_ARG = str(
    DEFAULT_RESEARCH_GO_PANEL_PATH.relative_to(REPO_ROOT)
    if DEFAULT_RESEARCH_GO_PANEL_PATH.is_relative_to(REPO_ROOT)
    else DEFAULT_RESEARCH_GO_PANEL_PATH
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export_research_go_panel",
        description=(
            "Export the sealed research GO panel (shared_risk_parity / "
            "PAPER-GO) as JSON; optionally push quantflow_research_go_* "
            "Prometheus gauges."
        ),
    )
    parser.add_argument(
        "--panel",
        default=DEFAULT_PANEL_ARG,
        help=(f"Path to the sealed performance panel (default: {DEFAULT_PANEL_ARG})"),
    )
    parser.add_argument(
        "--push-metrics",
        action="store_true",
        help="Push the snapshot fields into quantflow_research_go_* gauges",
    )
    args = parser.parse_args(argv)

    snapshot = load_research_go_panel(args.panel)
    if snapshot is None:
        print(
            json.dumps(
                {
                    "loaded": False,
                    "panel": args.panel,
                    "error": (
                        "research GO panel missing or invalid — fail-soft, "
                        "no metrics pushed (see logs)"
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2

    if args.push_metrics:
        update_research_go_panel_metrics(snapshot)

    print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
