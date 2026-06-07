# QuantFlow v0.1.3 Known Issues

发布日期：2026-06-07

## 已知限制

- 实盘凭证仍需通过环境变量注入。
- 可选 ML 依赖仍默认不安装。
- 当前交付仍是 Python CLI / Docker，不是桌面安装器产品。
- `requirements-lock.txt` 基于当前 Windows 干净 wheel 环境生成；若目标平台或 Python 次版本变化，需要重新生成对应锁文件。
- 远端 tag / release 资产仍需在最终发布动作中完成对齐和复核。
