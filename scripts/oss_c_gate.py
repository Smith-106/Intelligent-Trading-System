#!/usr/bin/env python3
"""Open-source path-C readiness gate (T020) — checklist runner, not a publish action.

Does **not** change GitHub visibility. Evaluates local hygiene required before
any human review of scheme C (core public):

  1) secret-scan on tracked-ish tree (heuristic; not a substitute for gitleaks history)
  2) demo pack check
  3) required docs present (CONTRIBUTING, LICENSE, decision brief, C checklist)
  4) .gitignore covers .env / data dumps
  5) optional: catalog hygiene + paper readiness config readable

Exit 0 = gate ready for *human* C decision; exit 1 = blockers remain.

    python scripts/oss_c_gate.py
    python scripts/oss_c_gate.py --json
    python scripts/oss_c_gate.py --quick   # skip demo pack rewrite paths
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# High-signal secret patterns (heuristic). False positives possible on docs.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("okx_secret_assign", re.compile(r"OKX_(?:SECRET|PASSPHRASE)\s*=\s*['\"][^'\"]{8,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_api_key_assign", re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key)\s*=\s*['\"][A-Za-z0-9_\-]{20,}")),
    ("sk_live", re.compile(r"sk-live-[A-Za-z0-9]{10,}")),
    ("telegram_bot", re.compile(r"\d{8,12}:[A-Za-z0-9_-]{30,}")),
]

SKIP_DIR_NAMES = {
    ".git",
    ".workflow",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "data",  # runtime artifacts; should not be in public tree
    "screenshots",
}
SCAN_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".txt",
    ".env",
    ".sh",
    ".ps1",
    ".ts",
    ".tsx",
    ".js",
}


def secret_scan(
    root: Path = REPO_ROOT,
    *,
    max_hits: int = 50,
) -> dict[str, Any]:
    """Heuristic secret scan of text files under repo (excludes data/)."""
    hits: list[dict[str, Any]] = []
    scanned = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        # Synthetic fixtures in unit tests often embed PEM/token shapes on purpose.
        # History scanners (gitleaks) still cover tests; heuristic gate focuses on product tree.
        if "tests" in path.parts:
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES and path.name not in {
            "Dockerfile",
            "Makefile",
            ".env.example",
        }:
            continue
        # Skip lock / huge generated
        if path.name.endswith(".lock") or path.stat().st_size > 1_500_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        for name, pattern in SECRET_PATTERNS:
            for m in pattern.finditer(text):
                # Allow obvious placeholders
                snippet = m.group(0)
                if any(
                    p in snippet.lower()
                    for p in (
                        "example",
                        "changeme",
                        "your_",
                        "xxx",
                        "placeholder",
                        "dummy",
                        "default-",
                        "default_",
                        "not-a-secret",
                        "test-only",
                    )
                ):
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                hits.append(
                    {
                        "rule": name,
                        "path": str(path.relative_to(root)).replace("\\", "/"),
                        "line": line_no,
                        "snippet": snippet[:80],
                    }
                )
                if len(hits) >= max_hits:
                    return {
                        "ok": False,
                        "scanned_files": scanned,
                        "hits": hits,
                        "truncated": True,
                        "note": "heuristic scan; also run gitleaks on full history before C",
                    }
    return {
        "ok": len(hits) == 0,
        "scanned_files": scanned,
        "hits": hits,
        "truncated": False,
        "note": "heuristic scan; also run gitleaks on full history before C",
    }


def check_required_docs(root: Path = REPO_ROOT) -> dict[str, Any]:
    required = [
        "LICENSE",
        "README.md",
        "CONTRIBUTING.md",
        "docs/research/open-source-decision-brief.md",
        "docs/research/open-source-c-gate-checklist.md",
        "docs/public-demo/PUBLISH.md",
        ".gitignore",
    ]
    missing = [p for p in required if not (root / p).is_file()]
    return {"ok": not missing, "missing": missing, "required": required}


def check_gitignore(root: Path = REPO_ROOT) -> dict[str, Any]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return {"ok": False, "reasons": ["no .gitignore"]}
    text = gi.read_text(encoding="utf-8", errors="replace")
    need = [".env", "*.key", "data/"]
    # data/ may be listed as /data or data/
    missing = []
    for n in need:
        if n == "data/":
            if "data/" not in text and "/data" not in text and "data/*" not in text:
                # many repos ignore specific data subdirs only — warn not fail
                missing.append("data/ (recommended explicit ignore for public C)")
        elif n not in text:
            missing.append(n)
    # Fail only on hard secrets ignores
    hard_missing = [m for m in missing if m in {".env", "*.key"}]
    return {
        "ok": not hard_missing,
        "missing": missing,
        "hard_missing": hard_missing,
    }


def check_demo_pack() -> dict[str, Any]:
    try:
        from scripts.demo_public_pack import check_pack  # type: ignore
    except Exception:
        # load by path
        import importlib.util

        path = REPO_ROOT / "scripts" / "demo_public_pack.py"
        spec = importlib.util.spec_from_file_location("demo_public_pack", path)
        if spec is None or spec.loader is None:
            return {"ok": False, "error": "cannot load demo_public_pack"}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.check_pack()
        return {"ok": rc == 0, "exit_code": rc}
    rc = check_pack()
    return {"ok": rc == 0, "exit_code": rc}


def check_ci_suggestions(root: Path = REPO_ROOT) -> dict[str, Any]:
    ci = root / ".github" / "workflows" / "ci.yml"
    oss = root / ".github" / "workflows" / "oss-c-gate.yml"
    return {
        "ok": ci.is_file(),
        "ci_yml": ci.is_file(),
        "oss_c_gate_yml": oss.is_file(),
        "note": (
            "Enable workflow_dispatch/oss-c-gate.yml before path C; "
            "main CI should stay green without publishing"
        ),
    }


def run_gate(*, quick: bool = False) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "docs": check_required_docs(),
        "gitignore": check_gitignore(),
        "secrets": secret_scan(),
        "ci": check_ci_suggestions(),
    }
    if not quick:
        checks["demo_pack"] = check_demo_pack()
    else:
        checks["demo_pack"] = {"ok": True, "skipped": True}

    blockers: list[str] = []
    for name, block in checks.items():
        if not block.get("ok", False):
            blockers.append(name)

    return {
        "kind": "oss_c_gate",
        "task": "T020",
        "ran_at": datetime.now(UTC).isoformat(),
        "ready_for_human_c_review": len(blockers) == 0,
        "blockers": blockers,
        "checks": checks,
        "visibility_note": (
            "This gate does NOT change GitHub visibility. Scheme B remains the "
            "published docs-demo path; scheme C requires explicit human approval."
        ),
        "next_human_steps": [
            "Review docs/research/open-source-c-gate-checklist.md",
            "Run gitleaks (or equivalent) on full git history",
            "Decide Apache-2.0 vs MIT for core if choosing C",
            "Only then consider Settings → visibility (manual)",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="Print full JSON report")
    ap.add_argument("--quick", action="store_true", help="Skip demo pack check")
    ap.add_argument(
        "--out",
        default="",
        help="Optional write report JSON path",
    )
    args = ap.parse_args()
    report = run_gate(quick=args.quick)

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"OSS C gate ready_for_human_c_review={report['ready_for_human_c_review']}")
        print(f"blockers={report['blockers'] or 'none'}")
        sec = report["checks"]["secrets"]
        print(f"secret_scan scanned={sec.get('scanned_files')} hits={len(sec.get('hits') or [])}")
        if sec.get("hits"):
            for h in sec["hits"][:10]:
                print(f"  HIT {h['path']}:{h['line']} [{h['rule']}] {h['snippet'][:60]}")
        docs = report["checks"]["docs"]
        if docs.get("missing"):
            print(f"missing docs: {docs['missing']}")
        print(report["visibility_note"])

    return 0 if report["ready_for_human_c_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
