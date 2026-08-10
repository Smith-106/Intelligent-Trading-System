# OSS 学习笔记：beijingcao/binance-deribit-btc

**Cloned**: 2026-08-10  
**Local path**: `C:/Users/niko/Desktop/oss-quant-benchmark/binance-deribit-btc`  
**Upstream**: https://github.com/beijingcao/binance-deribit-btc  
**对比对象**: QuantFlow（OKX paper-first 研究 OS，六层 + TradingSession）

---

## 1. 它是什么（产品定位）

| 维度 | binance-deribit-btc | QuantFlow |
|------|--------------------|-----------|
| 目标 | **跨所**：Deribit BTC **期权** + Binance USDT-M **永续** 套利/对冲 | **单所 OKX** 研究→paper→（可选）live |
| 节奏 | 亚秒扫描（`scan_interval_ms` 500）实时引擎 | 1h bar / paper 日课 / WFO 合同 |
| 核心资产 | 合成期权 vs 期货价差 + 交割 TWAP | 趋势/挑战者合同 + cost fidelity |
| 运维 | Redis 恢复、Telegram 遥控、Flask 面板 | Prometheus/告警、day-session、streak |

**结论**：可学的是 **生产运维/腿风险/执行门禁** 模式，不是把 QuantFlow 改成跨所期权套利。

---

## 2. 代码结构（可扫读）

```text
binance_deribit.py     # 入口
engine/                # Mixin 拼装的 RealTimeArbitrageEngine
  core.py              # 状态 + pause_reasons
  scanner / execution / risk / settlement / monitor / redis / ghost / startup / run
trade_executor.py      # 下单 + Binance 盘口就绪门禁
fee_calculator.py      # 费率档位
config.py              # 风控阈值 + ENV
db_store.py / telegram / binance-monitor (Flask)
```

规模约 **2.3 万行** Python；单文件 `settlement_mixin` / `execution_mixin` 达 2k+ 行 —— **Mixin 上帝对象**，与 QuantFlow 分层相反。

---

## 3. 值得学（映射到 QuantFlow）

| # | 模式 | 他们怎么做 | QuantFlow 可吸收方式 |
|---|------|------------|----------------------|
| 1 | **多源暂停原因集合** | `_pause_reasons: set`，非空即暂停；子系统各自 add/remove | KillSwitch / risk 告警用 **reason set**，避免单 flag 互盖 |
| 2 | **Preflight 启动检查** | `.env`、API、Redis、REST、持仓、磁盘 | 扩展 `preflight_baseline0_paper`：密钥形态、磁盘、Redis 可选 |
| 3 | **行情就绪门禁再下单** | `_binance_market_ready`：orderbook age / mark age | 与 W16 `update_orderbook` 联动：BBO **过期则拒单**（paper/live） |
| 4 | **Funding 开仓门** | `max_funding_rate_pct` 过高跳过 | paper/live 开仓前读 funding；B3 已有 funding 信号，可作 **risk gate** 非 alpha |
| 5 | **腿失败回滚** | 锚定腿成交后对冲失败 → IOC 回滚 + 二次重试 | 多腿/减仓路径：partial fill 后 **对侧失败要明确 rollback 策略**（文档化） |
| 6 | **裸腿 / 幽灵仓** | GhostMixin 对比 tracked vs exchange positions | 加深 `reconciliation`：未跟踪持仓告警（T021 方向） |
| 7 | **日损熔断** | `_daily_realized_pnl` + limit | RiskEngine 可选 **UTC 日损 cap**（默认关） |
| 8 | **状态恢复** | Redis 快照 + 重启重建 | paper/live checkpoint（默认关 overlay 已有）可对照 Redis 字段设计 |
| 9 | **费用显式分层** | FeeCalculator tier standard/vip | 已有 fee×slip + funding_tca；可补 **VIP 档配置表** 仅文档/配置 |
| 10 | **运维遥控** | Telegram pause/resume/调参 | 已有 TG 告警；可学 **命令白名单 + chat 校验** |
| 11 | **Decimal 金额** | 广泛 Decimal | 关键成交路径可逐步 Decimal（非紧急） |
| 12 | **落盘失败兜底** | SQLite 失败 → JSONL fallback | 监控/审计写失败时的 **append-only fallback** |

---

## 4. 明确不要抄

| 反模式 | 原因 |
|--------|------|
| 跨所期权-永续主产品 | 偏离 paper-first 研究 OS；双所+期权合规/保证金复杂度 |
| Mixin 巨石引擎 | 可测性差；QuantFlow 六层 + Protocol 更清晰 |
| 默认杠杆 20 / 测试网与实盘混在同一热路径 | 个人系统应 fail-closed 低杠杆 |
| 把「扫盘口套利」当 GO 叙事 | 无 WFO/合同；与 B0 成本后稳健期望无关 |
| 为学运维而引入 Redis 强依赖 | QuantFlow 可 **可选**；默认本地 paper 不应硬依赖 Redis |
| 无验证门的自动开仓 | 与 CPCV/DSR/paper_readiness 纪律冲突 |

---

## 5. 与当前 Option B 的衔接（可选后续，非必须）

| 优先级 | 想法 | 来源 |
|--------|------|------|
| P1 | Paper/live：**BBO 时间戳过期拒单** | trade_executor market_ready |
| P2 | Risk：**pause_reasons set** 统一熔断原因 | engine/core |
| P2 | Recon：**ghost position** 检查清单 | ghost_mixin |
| P3 | Preflight 项扩展（磁盘/可选 Redis） | README preflight |
| — | 不做：Deribit 适配、跨所扫描、期权合成引擎 | 产品边界 |

---

## 6. 一句话

> **binance-deribit-btc 是「跨所期权对冲实盘机器人」的运维与腿风险管理样本；QuantFlow 应偷师门禁/暂停/裸腿/费用/恢复，而不是偷师产品形态或 Mixin 巨石架构。**

*Study clone only — do not vendor into `quantflow/`.*
