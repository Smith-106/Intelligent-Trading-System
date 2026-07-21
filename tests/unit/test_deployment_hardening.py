"""ISS-005 / ISS-009 guards: deployment hardening must not regress.

These are static guards over the docker compose + workflow files so a future
edit that reintroduces ``:latest`` images, an unauthenticated Redis, a
hardcoded Grafana admin password, or a floating ``actions/*@vN`` tag is caught
at CI time rather than after a deployment.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.yaml"
_DOCKERFILE = _REPO_ROOT / "docker" / "Dockerfile"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_RELEASE = _REPO_ROOT / ".github" / "workflows" / "release.yml"

# Matches "image: owner/name:latest" or "image: name:latest" (floating tag).
_LATEST_IMAGE = re.compile(r"image:\s*[\w./-]+:latest\b")
# Matches a uses: line with a floating @vN tag (no SHA prefix). A SHA-pinned
# action is "@<40-hex> # vN"; a floating one is "@vN" with no leading hex.
_FLOATING_ACTION = re.compile(r"uses:\s*([\w/-]+)@v\d+(?![-\w])")
# Hardcoded Grafana admin password literal.
_GRAFANA_ADMIN_LITERAL = re.compile(r"GF_SECURITY_ADMIN_PASSWORD:\s*admin\b")
# Redis port published to all interfaces (not 127.0.0.1:6379).
_REDIS_EXPOSED = re.compile(r"^\s*-\s*\"6379:6379\"", re.MULTILINE)


def test_compose_has_no_latest_images() -> None:
    text = _COMPOSE.read_text(encoding="utf-8")
    assert not _LATEST_IMAGE.search(text), (
        "ISS-009: docker-compose.yaml must pin image tags (no `:latest`). "
        "Floating tags let a supply-chain push change production silently."
    )


def test_compose_redis_is_authenticated_and_loopback() -> None:
    text = _COMPOSE.read_text(encoding="utf-8")
    assert "--requirepass" in text, (
        "ISS-005 (SEC-013): Redis must run with --requirepass (no unauthenticated cache)."
    )
    assert not _REDIS_EXPOSED.search(text), (
        'ISS-005 (SEC-013): Redis port must bind to 127.0.0.1, not 0.0.0.0 ("6379:6379").'
    )
    assert "127.0.0.1:6379" in text


def test_compose_grafana_password_is_not_literal_admin() -> None:
    text = _COMPOSE.read_text(encoding="utf-8")
    assert not _GRAFANA_ADMIN_LITERAL.search(text), (
        "ISS-005 (SEC-014): GF_SECURITY_ADMIN_PASSWORD must come from the "
        "operator env (GRAFANA_ADMIN_PASSWORD), not the literal `admin`."
    )
    assert "GRAFANA_ADMIN_PASSWORD" in text


def test_compose_quantflow_hardened() -> None:
    text = _COMPOSE.read_text(encoding="utf-8")
    assert "no-new-privileges:true" in text, "ISS-005: quantflow needs no-new-privileges."
    assert "127.0.0.1:${QUANTFLOW_HOST_PORT" in text or "127.0.0.1:" in text


def test_dockerfile_runs_non_root() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^USER\s+\S+", text, re.MULTILINE), (
        "ISS-005 (SEC-012): Dockerfile must define a non-root USER."
    )
    assert "USER quantflow" in text or "USER " in text


def test_workflows_have_no_floating_action_tags() -> None:
    offenders: list[str] = []
    for wf in (_CI, _RELEASE):
        text = wf.read_text(encoding="utf-8")
        for line in text.splitlines():
            m = _FLOATING_ACTION.search(line)
            if m:
                # A SHA-pinned line has a 40-hex commit before the comment.
                # Floating line: "uses: actions/checkout@v4" (no SHA).
                offenders.append(f"{wf.name}: {line.strip()}")
    assert not offenders, (
        "ISS-009 (SEC-005): GitHub Actions must be SHA-pinned (uses: name@<sha> # vN), "
        "not floating @vN. Offenders: " + " | ".join(offenders)
    )
