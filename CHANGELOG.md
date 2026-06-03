# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [0.1.1] - 2026-06-03

### Added
- Added `scripts/build_release.py` to build release artifacts, checksums, and a release manifest from one command.
- Added `.github/workflows/release.yml` to publish GitHub Release assets from a `vX.Y.Z` tag.
- Added `dist/SHA256SUMS.txt` and `dist/release-manifest.json` as release metadata outputs.

### Changed
- Promoted the release process from manual artifact collection to a tag-driven, repeatable workflow.
- Updated release documentation to treat automated release publication as part of the delivery standard.
- Reserved `v0.1.0` as the historical baseline and moved the current release candidate to `v0.1.1` for source/tag consistency.

## [0.1.0] - 2026-06-03

### Added
- Added four new strategy templates: `volatility_breakout`, `funding_rate`, `momentum_rotation`, and `ml_ensemble`.
- Added package build verification and CLI smoke checks to GitHub Actions CI.
- Added release documentation set under `docs/release/v0.1.0/`.
- Added `requirements-lock.txt` for reproducible environment capture.
- Added SHA256 checksum files for source and wheel distributions.

### Changed
- Hardened Docker packaging and compose deployment flow for clean install and health checks.
- Improved installed-package runtime path handling for CLI config resolution.
- Improved environment preflight checks in `scripts/check_env.py`.
- Tightened backtest correctness around equity continuity and trade PnL handling.
- Raised release readiness with packaging, deployment, and verification artifacts.

### Fixed
- Fixed release-chain runtime issues affecting packaged CLI execution.
- Fixed transient data fetch failure handling so the trading loop retries instead of terminating.
- Fixed `ruff format` drift caught by CI.
- Fixed missing runtime dependency on `scikit-learn`.

### Security
- Verified no hard-coded live credentials are present in tracked source files.

### Known Issues
- Real exchange execution still requires operator-provided environment variables such as `OKX_API_KEY`, `OKX_SECRET`, and `OKX_PASSPHRASE`.
- Optional ML extras such as `torch` and `transformers` are not installed by default and must be added explicitly when enabling the corresponding strategy path.
