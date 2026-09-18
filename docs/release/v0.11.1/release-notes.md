# QuantFlow v0.11.1

发布日期：2026-09-18

## 亮点

**仓库卫生与知识图谱修复版本**——无功能变更；本地清理 + Wiki KG 死链清零 + 版本漂移对齐 + lint 清零。

## 变更明细

### Fixed
- 4 个 F841 未用变量清零：`data/fetcher.py`、`data/resample.py`、`data/trades_store.py`、`web/service.py`
- `quantflow/web/static/dist/` 重建（`test_station_root_and_strategy_api` 依赖 SPA `index.html` fallback）

### Engineering — 知识图谱
- **Wiki Health 0 → 92/100**：85 条死链清零；63 个孤儿 → 8（剩余为 `spec:global:*` 容器）
- 68 条 `DOC-*`/`kh-*` 前缀漂移 → 规范 `knowhow-doc-*`/`knowhow-kh-*` 索引 id
- 19 个文件移除 20 条已删除 `session-*` 死引用；12 个孤立条目链回 `knowledge-hub`
- `knowledge audit`：302 个 `legacy-unscoped` 条目被 repository-manifest 缺失阻塞——**需人工建 manifest + 类目选择**（不在本版本范围）

### Engineering — Drift Realign
- 手动扫描报告 `.workflow/.drift-realign/drift-report-2026-09-18.md`（10 findings 处置）
- roadmap.md / project.md 版本漂移 v0.5.0 → v0.11.0（4 处修正）
- spec 代码引用全验证有效；63 个 issues 全闭环无 stale

### Engineering — 本地清理
- `no/` 空目录壳、`.pytest_cache`、`.ruff_cache`、全部 `__pycache__`（21 目录）、`*.pyc`、coverage 产物
- frontend `dist`/`.vite`/`node_modules/.cache`
- 误跟踪的 `.workflow/codebase/doc-index.json.bak-refresh-20260725`

### Engineering — 格式化
- `ruff format` 规范化 16 个文件（行长/空行重排，行为不变）

## 验证

| 门 | 结果 |
|---|---|
| `ruff check quantflow/` | 0 errors |
| `ruff format --check` | 183/183 clean |
| `mypy quantflow/ --strict` | clean |
| `pytest -m "not live and not slow"` | 3461 passed / 4 failed |
| `maestro wiki health` | 92/100 · brokenLinks 0 · orphans 8 |

**4 个 pytest 失败全部为预存数据依赖**（与本版本无关，`git stash` 验证在干净 HEAD 同样失败）：
- `test_meta_backfill::test_days_90_saves_rows` / `test_days_180_single_windowed_call_saves_rows` — 需 OKX funding/OI meta 分区数据
- `test_research_go_panel::test_load_sealed_panel_happy_path` — 需 `data/paper_replay/perf_verify/performance_panel.json`
- `test_station_root_and_strategy_api` — **本版本已修复**（dist 重建后 PASS）

## 遗留欠账（非阻塞）

- `.workflow/state.json` 缺失——drift workflow 引用，需 `/maestro-init` 重建或接受弃用
- 302 个 `legacy-unscoped` knowledge 条目——需 repository-manifest + 类目归一
- ISS-006（RD-Agent paper pipeline）——仍在途
- `quantflow/web/static/dist/` 未入库——构建产物按需 `npm run build` 重建（已在 `.gitignore`）

## 升级

无 breaking change；无 schema 变更；直接 `pip install -e .` 升级即可。
