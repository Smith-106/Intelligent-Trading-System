# QuantFlow v0.11.2

发布日期：2026-09-18

## 亮点

**知识归一化收尾版本**——无功能变更；`repository.json` 仓库身份补齐后，302 个 `legacy-unscoped` knowledge 条目完成 canonical 归一化，`knowledge audit` 643 → **1** findings。

## 变更明细

### Engineering — Knowledge Normalize
- **`.workflow/repository.json`**：仓库身份清单 `{repo_id: UUID, repo_name: quantflow}`——解除 `legacy-unscoped→current-repo-id` 归一化的全局阻塞（此前 302 条目全卡 `legacy-unscoped-requires-repository-manifest`）
- **`maestro knowledge normalize`** 两轮 apply（28 + 39 files），audit findings 643 → 1（仅余 P2 `stale-active-observation`，非阻塞）
- **40 个 knowhow 文件**：`type: knowhow` → `document`（canonical enum：`session|tip|template|recipe|reference|decision|asset|blueprint|document`）
- **11 个 spec entry**（`specs/learnings.md`）：自由 category `pattern|antipattern|gotcha|quality|technique` → canonical `learning|debug|test`
- **26 个 knowhow + learnings.md**：按语义分配 canonical category（`arch|coding|debug|test|review|learning|ui`）

### Engineering — State
- **`.workflow/state.json`** 重建（v2.0 结构对齐历史模板）：`M5` 完成、`current_task=ISS-006-rdagent-paper-pipeline`、key_decisions/blockers/deferred 补齐当前真实状态
  - 注意：state.json 在 `.gitignore` 内——本地运行时状态设计上不入库（v0.5.0 时被删属正常清理，非缺失 bug）

### Engineering — Issue Wording
- **ISS-006 语义校正**（`project.md`）：区分「skeleton/CLI 接线已 `resolved`（ISS-20260803-006 / ISS-20260804-001）」与「RD-Agent 全 LLM 管道 `research→train→register(paper)` 在途」——前者是 issue 闭环事实，后者是研究路线图项

### Docs
- **README**：补 `quantflow/web/static/dist/` 构建产物说明——`cd frontend && npm run build` 生成；Station 运行 + `test_station_root_and_strategy_api` 依赖 `index.html` SPA fallback，**勿删除**（v0.11.1 曾误删致 1 测试回归）

## 验证

| 门 | 结果 |
|---|---|
| `maestro knowledge audit` | 643 → **1** findings（仅 P2 stale-active-observation，非阻塞） |
| `maestro wiki health` | **92/100** · brokenLinks 0 · orphans 8（spec:global:* 容器） |
| `ruff check quantflow/` | 0 errors |
| `mypy quantflow/ --strict` | clean |
| `pytest -m "not live and not slow"` | 3461 passed / 4 pre-existing failures（数据依赖，与本版本无关） |
| `git status` | 工作树干净，远程 main/tag 同步 |

## 遗留欠账（非阻塞）

- ISS-006 全 LLM 管道（`research→train→register(paper)` 真实驱动）——研究路线图项
- 4 个 pytest 数据依赖失败：funding/OI meta 分区 + `perf_verify/performance_panel.json` 缺失
- `.workflow/.trash/knowledge-normalize-2026-09-18T*` 备份（>30 天可清）

## 升级

无 breaking change；无 schema 变更；直接 `pip install -e .` 升级即可。
