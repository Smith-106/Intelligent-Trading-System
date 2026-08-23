---
title: 发布文档目录形态是release CI硬依赖
type: decision
created: 2026-08-23T14:57:51.412Z
---

本项目 release.yml 对发布文档的形态有硬依赖：scripts/build_release.py 的 ensure_release_docs 要求 docs/release/vX.Y.Z/ 目录下存在 7 个固定文件（release-notes/upgrade-guide/rollback-plan/known-issues/test-report/security-report/release-standard-quantflow）。v0.5~v0.10 期间改用了扁平 vX.YZ.md 单文件惯例，导致 v0.10.0 的 tag 虽然打了但 Release 从未成功生成（FileNotFoundError）。自 v0.11.0 起恢复目录形态；扁平 md 只能作为 README 快速链接的补充，不可替代目录。另：tag 必须是 annotated（v0.9/v0.10 曾退化为轻量）；顺序为先 push main 再 push tag。
