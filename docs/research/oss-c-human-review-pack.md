# OSS 方案 C — 人审包（T030）

**Status**: 材料刷新；**不是**公开批准  
**Visibility**: **仅人类**可改；Agent **禁止** `gh repo edit --visibility`  
**当前公开路径**: 方案 **B**（docs-demo）  
**工程门禁**: `python scripts/oss_c_gate.py`（T020）

Related: [open-source-c-gate-checklist.md](./open-source-c-gate-checklist.md) · [open-source-decision-brief.md](./open-source-decision-brief.md)

---

## 1. 决策表（人填）

| 问题 | 选项 | 你的决定 | 日期 |
|------|------|----------|------|
| 是否离开 B、评估 C？ | Stay B / Start C review / Defer | _ | _ |
| 接受 PR/issue 维护成本？ | Yes / No | _ | _ |
| Core LICENSE | MIT（根） / Apache-2.0 / 统一后再公开 | _ | _ |
| 研究产物（gate.json、全窗 PnL） | 默认私有 / 部分脱敏公开 | _ | _ |
| 成功指标 | **非 stars**；成本后 paper-first OS | 确认 / 否 | _ |
| 复审触发 | 日期：______ 或 paper 日课稳定 + ≥N 合同 | _ | _ |

**冻结约束（工程）**

- `portfolio_optimization.enabled=false` 在 default 保持，除非有意变更  
- cost_fidelity / funding_tca / paper_readiness **不得**为 OSS 放宽  
- `data/paper_replay/**` 研究 dump **不** force-add  

---

## 2. 自动门禁（每次人审前）

```bash
python scripts/oss_c_gate.py
python scripts/oss_c_gate.py --json
python scripts/oss_c_gate.py --quick
```

期望：`ready_for_human_c_review=true`，exit 0。

| 检查 | 证明 |
|------|------|
| docs | CONTRIBUTING, LICENSE, brief, checklist, PUBLISH |
| gitignore | `.env` / keys；建议忽略 `data/` |
| secrets | 树启发式（**非**全历史） |
| demo_pack | docs-demo 无密钥 |
| ci | 根 CI + 可选 `oss-c-gate.yml` |

---

## 3. gitleaks / 全历史（人执行）

自动 `oss_c_gate` **不能**替代全历史扫描。

### 推荐（Docker）

```bash
docker run -v "%CD%":/repo -w /repo zricethezav/gitleaks:latest detect --source . --verbose
```

### 本地二进制

```bash
# 安装后：
gitleaks detect --source . --report-path gitleaks-report.json
```

### 发现密钥时

1. **轮换**全部命中凭证  
2. 从历史移除或作废（按组织流程）  
3. 再跑 `oss_c_gate` + gitleaks  
4. **在轮换完成前禁止** visibility 变更  

### TruffleHog 备选

```bash
trufflehog git file://. --only-verified
```

---

## 4. 人审勾选（T030）

- [ ] §1 决策表已填  
- [ ] `oss_c_gate.py` 绿  
- [ ] gitleaks（或等价）全历史已跑并归档报告路径：`_______________`  
- [ ] 无私有 paper_sessions / 全窗成本 JSON 被误提交  
- [ ] README 仍是 paper-first + Path A/B + non-goals  
- [ ] CI 计划：`pytest -m "not live"`、ruff、demo pack、`oss_c_gate --quick`  
- [ ] **不**将 “改 visibility” 写进 CI  
- [ ] 若批准 C：仅人类在 GitHub Settings 操作  

---

## 5. Agent 禁令（重申）

| 禁止 | 原因 |
|------|------|
| `gh repo edit --visibility *` | 人审专属 |
| force-add `data/**` 研究产物 | 泄漏/体量 |
| 放宽 GO/cost/paper_readiness | 北极星 |
| 将 B 路径改成“已公开 core”叙事 | 事实仍是 B |

---

## 6. T030 工程 done

- [x] 本文件（决策表 + gitleaks 指引）  
- [x] checklist 交叉链接  
- [x] `oss_c_gate` 可重复跑  
- [ ] **人类** gitleaks 与 visibility（不在 agent 范围）  
