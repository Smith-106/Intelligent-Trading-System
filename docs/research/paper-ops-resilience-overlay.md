# Paper ops：checkpoint / reconciliation 可选开启（T029）

**Status**: 文档 + overlay 交付；**默认仍关**（`default.yaml`）  
**相关**: [baseline0-paper-run-checklist.md](./baseline0-paper-run-checklist.md) · `scripts/resilience_drill.py` · T021

---

## 1. 默认姿态（不可破）

| 开关 | `default.yaml` | 含义 |
|------|----------------|------|
| `state.enabled` | **false** | 不写/不恢复 checkpoint |
| `reconciliation.enabled` | **false** | 不跑周期对账 |

理由：paper-first 冷启动零行为变化；损坏 checkpoint 与漂移告警已在 T021 drill 验证，**开启是运维决策**。

---

## 2. 开启前强制清单

- [ ] `python scripts/resilience_drill.py` → **overall=pass**（A 坏 JSON / B schema / C 漂移 critical / D 匹配无告警）
- [ ] 理解 fail-closed：坏 checkpoint → `load=None` + `last_error`，**拒绝当正常恢复**
- [ ] 漂移路径：`run_daily_reconciliation` → `_emit_drift_alert` → MonitoringSink **critical** / `reconciliation_drift`
- [ ] 告警通道已配置（或接受仅日志）
- [ ] **仅 paper**（本 overlay 不授权 live）
- [ ] **不要**把 `default.yaml` 默认改成 true 并提交为“全员默认”

---

## 3. Overlay 文件

`quantflow/config/paper_ops_resilience_overlay.yaml`

```yaml
state:
  enabled: true
  checkpoint_dir: "./data/checkpoints"
  checkpoint_interval_minutes: 5

reconciliation:
  enabled: true
  interval_minutes: 5
  drift_threshold_bps: 100
  order_staleness_seconds: 300
```

### 与 Baseline-0 日课组合

1. 成本/RP：`paper_baseline0_overlay.yaml`（taker/slip 0.1% + symbol RP）  
2. 韧性：`paper_ops_resilience_overlay.yaml`（仅当 §2 勾完）

若 CLI 只吃一个 `--config`：复制合并到**本地** operator yaml（勿提交密钥；勿把 RP+state 误写进 default）。

---

## 4. 运行中观察

| 项 | 期望 |
|----|------|
| checkpoint 目录 | `data/checkpoints/` 周期性出现快照 |
| 进程重启 | 恢复成功才允许新开仓语义（fail-closed） |
| 对账 | 间隔到点；账本一致无 critical；人为漂移应 critical |
| 停用 | 去掉 resilience overlay / 设回 enabled false；**default.yaml 保持 false** |

---

## 5. 故障

| 现象 | 动作 |
|------|------|
| 启动即 last_error | 删/隔离坏 checkpoint，查 schema；勿强行改 JSON 骗过 |
| 频繁 drift alert | 先停会话；对账本地 vs gateway；勿关阈值装看不见 |
| drill 红 | **禁止**开启 overlay |

---

## 6. 非目标

- 默认打开全站 checkpoint/recon  
- 用 overlay 代替 live 验收  
- 跳过 resilience_drill  
