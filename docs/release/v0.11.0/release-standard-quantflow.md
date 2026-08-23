# QuantFlow 发布标准（v0.11.0 适用）

## 版本语义
- 后端 `quantflow` 与前端 `quantflow-station` 各自独立 SemVer 演进
  （本版起明确文档化：后端 0.11.0 / 前端 0.4.0）
- 发布 commit 必须同时含：pyproject version、quantflow/__init__.py __version__、
  CHANGELOG 段头定稿、docs/release/vX.Y.Z/ 七件套

## 发布前置门禁（全部本地重跑，不可复用旧产物）
1. 后端：ruff check/format + 三分区 pytest -m "not slow" 全绿
2. 前端：tsc -b + oxlint + npm run build + npm test (vitest) 全绿
3. `python scripts/build_release.py --tag vX.Y.Z` 通过 Version mismatch 校验

## Tag 规范
- 格式 `vX.Y.Z`，**annotated tag**（v0.9.0/v0.10.0 曾退化为轻量，自本版恢复惯例）
- 顺序：先 push main（发布 commit），后 push tag（触发 release.yml）

## 发布文档形态
- **目录形态** `docs/release/vX.Y.Z/`（7 文件）是 release.yml 的硬依赖——
  扁平 `vX.Y.Z.md` 会导致 ensure_release_docs FileNotFoundError（v0.10.0 教训）
- 扁平 .md 可选保留供 README 快速链接，但不可替代目录
