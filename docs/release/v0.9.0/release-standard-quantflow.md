# QuantFlow 发版标准（v0.9.0 适用）

1. 版本三处同步：pyproject.toml / quantflow/__init__.py / CHANGELOG.md
2. docs/release/vX.Y.Z.md 单页 + docs/release/vX.Y.Z/ 七件套（notes/upgrade/rollback/known-issues/test/security/standard）
3. `python scripts/build_release.py --tag vX.Y.Z` 生成 wheel+sdist+SHA256+manifest
4. tag `vX.Y.Z` push 触发 release.yml（quality gates → build → GitHub Release）
5. 发布后冒烟：gh release view、wheel 安装、CLI status
6. 冻结不变量：B0/B3–B5 不解冻；promotion_eligible 恒 false；parity 仅 paper↔live
