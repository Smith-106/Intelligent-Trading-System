# KOL / Discord 工作冻结存档（Deferred Plan）

**状态**：⏸ **DEFER** — 智能交易系统主线完成后再做  
**冻结日期**：2026-08-11  
**仓库 HEAD 参考**：`5de499e`（含 notify 增量拉取）  
**恢复入口**：本文 + `docs/research/kol-member-near-realtime-sync.md` + `docs/research/kol-discord-aggregation.md`

---

## 1. 目标（恢复时不变）

付费 Discord KOL 群（如 Kolunite）的：

1. **市场评估 + 带单文本/图** 聚合  
2. 输出 **可审计共识**（非自动跟单）  
3. 可选 **参考权重** 缩放系统仓位（同向略加、反向略减）  
4. 无管理员 Bot 时用 **准实时导出 / 通知触发增量拉**

**硬约束**：

- 默认 **不 copy-trade**；`kol_reference.enabled=false` 直到证据健康  
- **不**实现用户 Token 自机器人 / Gateway self-bot（违 Discord ToS）  
- Token / 导出 / 附件 **永不 commit**（`data/kol_*` 已 gitignore）  
- paper-first；与 B0/B3–B5 冻结包解耦

---

## 2. 已完成（勿重做）

| 模块 | 路径 / Commit 锚点 |
|------|-------------------|
| 信号模型 + 解析 + 共识 | `quantflow/strategy/kol_signals/{models,parser,aggregator}.py` |
| 源表 / 审计存储 | `registry.py`, `store.py`；`quantflow/config/kol_registry.yaml` |
| Discord 入站 + TV 图 OCR 钩子 | `discord_ingest.py`, `chart_ocr.py` |
| 参考权重 + 仓位接线 | `reference_weight.py`；`PositionSizer.reference_multiplier`；`engine._kol_reference_multiplier`；`KolReferenceConfig` |
| CLI | `scripts/kol_discord_ingest.py`（export / poll / consensus / reference） |
| 准实时定时 | `scripts/kol_export_loop.ps1`, `kol_near_realtime_tick.ps1`, `kol_channels.txt` |
| 通知触发增量 | `scripts/kol_on_notify_pull.ps1`, `kol_notify_watch_folder.ps1` |
| 文档 | `kol-discord-aggregation.md`, `kol-member-near-realtime-sync.md`（§8–11 调研+事件触发） |
| 测试 | `tests/unit/test_kol_signals.py`, `test_kol_reference_weight.py` |
| 配置默认关 | `default.yaml` → `kol_reference.enabled: false` |

代表提交链（由旧到新）：

```text
e7dba93  KOL 管道
926d156  成员连接路径
2818517  参考权重
0fb82f7  准实时方案
d3cb70d  无管理员实时调研
4c5b4c4  export_loop
c53c363  第三方导出对照
d5ff4bd  on-notify 增量
5de499e  gitignore notify inbox
```

---

## 3. 恢复后待办（按优先级）

### P0 — 跑通真实数据环（不改产品主线）

1. 本机安装 DiscordChatExporter CLI  
2. 仅环境变量设置 `DISCORD_USER_TOKEN`（风险自担）或拿到管理员 **只读 Bot** 后用 `poll`  
3. 填 `scripts/kol_channels.txt` + `kol_registry.yaml` 权重  
4. 单次：`kol_export_loop.ps1 -Once` 或 `kol_on_notify_pull.ps1`  
5. 检查 `data/kol_signals/latest_consensus.json` / `latest_reference.json`  
6. 健康后再考虑 `kol_reference.enabled=true`（仅 paper）

### P1 — 通知挂钩（可选）

- 桌面 toast / Power Automate → 写 `data/kol_notify_inbox/`  
- 或常驻 `kol_notify_watch_folder.ps1` + 定时 `export_loop` 兜底（15–30min）

### P2 — 产品增强（系统主线稳后再议）

- [ ] FinBERT / 现有 `sentiment.py` 叠进 aggregator  
- [ ] Grafana 面板：共识 score / reference_multiplier  
- [ ] 管理员 Bot 正式 `poll` 路径文档化 + 密钥轮换  
- [ ] OCR：tesseract 实装验证（现默认 stub/auto）  
- [ ] 增量包装 [DCE-incrementalBackup](https://github.com/slatinsky/DiscordChatExporter-incrementalBackup) 评估  
- [ ] 多 symbol 系统 side 自动从持仓/策略状态注入（现 CLI `--system-side`）

### 明确不做（除非政策变）

- 用户 Token 常驻 Gateway / self-bot 接入 QuantFlow  
- 自动跟单 live  
- 把付费群内容二次公开或上传不明 SaaS

---

## 4. 恢复时最小命令清单

```powershell
$env:PYTHONUTF8 = "1"
cd "C:\Users\niko\Desktop\智能交易系统"

# 单测
python -m pytest tests/unit/test_kol_signals.py tests/unit/test_kol_reference_weight.py -q

# 离线：已有 export JSON
pwsh -File .\scripts\kol_near_realtime_tick.ps1 -SystemSide "BTC/USDT=long"

# 有 Token：通知增量 或 定时
# pwsh -File .\scripts\kol_on_notify_pull.ps1
# pwsh -File .\scripts\kol_export_loop.ps1 -Once

# 仅看参考权重（需 consensus 文件）
python .\scripts\kol_discord_ingest.py reference --system-side BTC/USDT=long
```

---

## 5. 与主线关系

| 主线（智能交易系统） | KOL/Discord（本存档） |
|----------------------|------------------------|
| 数据/回测/paper/live/风控 | **旁路辅助**，默认关 |
| B0 与冻结包 | **不得**因 KOL 改动而破坏 |
| 成功标准 vs-BTC | KOL **不计入** alpha 主证据 |

恢复条件建议：

1. 主线 paper/live 路径稳定、用户宣布「系统完成一阶段」  
2. 再开 P0 真实频道接入  
3. paper 观察 reference 行为 ≥ 约定天数后再谈是否保持 enabled

---

## 6. 一句话

> **KOL/Discord 管道与「通知触发增量拉」已代码+文档就绪；默认关闭，整包冻结。智能交易系统主线完成后再做真实群接入与可选增强。**
