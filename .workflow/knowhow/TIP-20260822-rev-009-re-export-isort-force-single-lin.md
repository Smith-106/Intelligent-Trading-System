---
title: "REV-009: re-export 在 isort force-single-line 下用赋值形式"
type: tip
created: 2026-08-22T08:24:34.453Z
---

背景：odyssey REV-009 S4 将 cli/main.py 渲染辅助抽到 cli/render.py。
教训：import 形式 re-export（from x import y as y）会被 pyproject 的 isort force-single-line 拆行并遭 F401 自动修剪，ruff --fix 静默删除符号导致测试 AttributeError。稳定做法：模块中段用赋值形式 _display_cpcv = _cli_render._display_cpcv + noqa E402。
适用：任何拆文件但保持 monkeypatch 字符串路径契约的重构（本项目 82 处 patch 字符串目标）。
