#!/usr/bin/env python3
"""Build QuantFlow release artifacts and checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
PACKAGE_INIT_PATH = REPO_ROOT / "quantflow" / "__init__.py"
DIST_DIR = REPO_ROOT / "dist"
DOCS_DIR = REPO_ROOT / "docs" / "release"


def load_project_version() -> str:
    with PYPROJECT_PATH.open("rb") as f:
        data = tomllib.load(f)
    return str(data["project"]["version"])


def load_package_version() -> str:
    version_line = next(
        line
        for line in PACKAGE_INIT_PATH.read_text(encoding="utf-8").splitlines()
        if "__version__" in line
    )
    return version_line.split("=", maxsplit=1)[1].strip().strip('"')


def run_build() -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(DIST_DIR)],
        cwd=REPO_ROOT,
        check=True,
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(version: str) -> list[dict[str, str]]:
    asset_names = [
        f"quantflow-{version}.tar.gz",
        f"quantflow-{version}-py3-none-any.whl",
    ]
    checksums: list[dict[str, str]] = []
    for name in asset_names:
        asset_path = DIST_DIR / name
        if not asset_path.exists():
            raise FileNotFoundError(f"Missing release artifact: {asset_path}")
        digest = sha256_of(asset_path)
        checksum_path = DIST_DIR / f"{name}.sha256"
        checksum_path.write_text(f"{digest} *{name}\n", encoding="utf-8")
        checksums.append(
            {
                "name": name,
                "sha256": digest,
                "path": str(asset_path),
                "checksum_path": str(checksum_path),
            }
        )

    summary_lines = [f"{item['sha256']} *{item['name']}" for item in checksums]
    (DIST_DIR / "SHA256SUMS.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return checksums


def ensure_release_docs(version: str) -> Path:
    release_dir = DOCS_DIR / f"v{version}"
    required = [
        release_dir / "release-notes.md",
        release_dir / "upgrade-guide.md",
        release_dir / "rollback-plan.md",
        release_dir / "known-issues.md",
        release_dir / "test-report.md",
        release_dir / "security-report.md",
        release_dir / "release-standard-quantflow.md",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    if missing:
        missing_text = ", ".join(missing)
        raise FileNotFoundError(f"Missing release documentation: {missing_text}")
    return release_dir


def write_manifest(
    version: str, tag: str, checksums: list[dict[str, str]], release_dir: Path
) -> Path:
    manifest_path = DIST_DIR / "release-manifest.json"
    payload = {
        "version": version,
        "tag": tag,
        "release_dir": str(release_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
        "notes_file": str((release_dir / "release-notes.md").relative_to(REPO_ROOT)).replace(
            "\\", "/"
        ),
        "assets": [
            {
                "name": item["name"],
                "sha256": item["sha256"],
                "path": str(Path(item["path"]).relative_to(REPO_ROOT)).replace("\\", "/"),
                "checksum_path": str(Path(item["checksum_path"]).relative_to(REPO_ROOT)).replace(
                    "\\", "/"
                ),
            }
            for item in checksums
        ],
        "checksum_bundle": "dist/SHA256SUMS.txt",
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build release artifacts for QuantFlow.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing dist artifacts.")
    parser.add_argument("--tag", default="", help="Expected release tag, for example v1.2.3.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = load_project_version()
    package_version = load_package_version()
    if version != package_version:
        raise ValueError(
            f"Version mismatch: pyproject.toml={version}, quantflow/__init__.py={package_version}"
        )

    expected_tag = f"v{version}"
    if args.tag and args.tag != expected_tag:
        raise ValueError(f"Tag mismatch: expected {expected_tag}, got {args.tag}")

    DIST_DIR.mkdir(exist_ok=True)
    release_dir = ensure_release_docs(version)
    if not args.skip_build:
        run_build()
    checksums = write_checksums(version)
    manifest_path = write_manifest(version, args.tag or expected_tag, checksums, release_dir)

    print(f"Release version: {version}")
    print(f"Release tag: {args.tag or expected_tag}")
    print(f"Release notes: {(release_dir / 'release-notes.md').relative_to(REPO_ROOT)}")
    for item in checksums:
        print(f"Asset: {item['name']} sha256={item['sha256']}")
    print(f"Manifest: {manifest_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
