# Baseline-0 日常 Paper 操作检查清单

**用途**：把 [Candidate Baseline-0](./Candidate-Baseline-0.md) 的**组合/成本/标的合同**接到日常  
`quantflow run --mode paper`，而不是交易 live。

**合同摘要**

| 项 | 值 |
|----|-----|
| 模式 | **paper only** |
| 策略 | `trend_following`（默认 `entry_structure=classic`） |
| 标的 | `BTC/USDT,ETH/USDT,SOL/USDT` |
| 周期 | `1h` |
| 组合 | 共享账本 + `portfolio_optimization.level=symbol` + `risk_parity` |
| 再平衡 | 每 48 个**唯一时间戳**（约 2 天 @1h） |
| 成本 | taker 0.1% / slip 0.1% |
| 配置 | `quantflow/config/paper_baseline0_overlay.yaml` |
| 研究门控结果 | [Candidate-Baseline-0-results.md](./Candidate-Baseline-0-results.md) → **PAPER-GO** |

---

## 0. 两条路径（先选对）

| 路径 | 命令 | 含 nested 方向门？ | 用途 |
|------|------|-------------------|------|
| **A. 日常 paper 会话** | `quantflow run --mode paper …` | **否**（CLI 未接线 gate wrapper） | 模拟盘常开、观察订单/组合/RP 再平衡 |
| **B. 研究复现 / GO 核对** | `python scripts/run_baseline0.py` | **是**（`paper_replay` nested） | 与 Baseline-0 候选卡数字对齐 |

> 日常清单默认走 **路径 A**。若要和 WFO 候选卡 byte 级语义对齐，用 **路径 B**，不要拿路径 A 的 PnL 直接对比 `gate.json`。

---

## 1. 启动前（Pre-flight）— 全部勾选再 run

### 1.1 环境

- [ ] 已在仓库根目录：`C:/Users/niko/Desktop/智能交易系统`（或本机等价路径）
- [ ] 虚拟环境已激活，且 `python -c "import quantflow; print(quantflow.__version__)"` 为 **0.5.x**
- [ ] **不要**设置交易 live 所需密钥来“顺便试 live”；本清单 **禁止** `--mode live`
- [ ] Paper 不需要 `OKX_API_KEY`；若环境里有 live key，确认 CLI 使用 `--mode paper` 且不会误触 live

一键预检（推荐）：

```bash
python scripts/preflight_baseline0_paper.py
```

### 1.0 单命令 day-session（P0 T004，推荐）

路径 A 全编排：preflight → 摘要工件 →（可选）启动 paper run。

```bash
# 只做预检 + 写 data/paper_sessions/latest.json
python scripts/paper_day_session.py

# 预检通过后前台启动 paper（Ctrl-C 停止）
python scripts/paper_day_session.py --start-run

# 失败时尝试告警钩子
python scripts/paper_day_session.py --alert-on-fail
```

退出码 `0` = 可启动；非 0 = 按输出修。

### 1.2 数据（1h 三币）

- [ ] 本地 Parquet 有 `BTC/USDT`、`ETH/USDT`、`SOL/USDT` 的 **1h** 历史
- [ ] 最近 bar 不过度陈旧（建议：最新时间戳距今 **&lt; 48h**；研究复现可放宽）

```bash
# 不足时补数（按需）
quantflow download --symbol BTC/USDT --timeframe 1h
quantflow download --symbol ETH/USDT --timeframe 1h
quantflow download --symbol SOL/USDT --timeframe 1h
```

### 1.3 配置合同

- [ ] Overlay 存在：`quantflow/config/paper_baseline0_overlay.yaml`
- [ ] 确认 **未** 把 `default.yaml` 里 `portfolio_optimization.enabled` 改成 true（默认保持 false；日常用 overlay 显式开启）
- [ ] Overlay 关键项与合同一致：

```yaml
execution.mode: paper
execution.taker_fee: 0.001
execution.slippage: 0.001
risk.portfolio_optimization.enabled: true
risk.portfolio_optimization.method: risk_parity
risk.portfolio_optimization.level: symbol
risk.portfolio_optimization.rebalance_every_n_bars: 48
```

抽查：

```bash
python -c "from quantflow.common.config import load_config; c=load_config('quantflow/config/paper_baseline0_overlay.yaml'); po=c.risk.portfolio_optimization; print(c.execution.mode, c.execution.taker_fee, c.execution.slippage, po.enabled, po.level, po.rebalance_every_n_bars)"
# 期望: paper 0.001 0.001 True symbol 48
```

### 1.4 策略与符号

- [ ] 策略名：`trend_following`（不要误加 `mean_reversion` 除非你在做对照实验）
- [ ] 符号列表完整三币（少一币 = 不是 Baseline-0 组合合同）
- [ ] timeframe：`1h`；poll interval：建议 `60`（秒）

---

## 2. 启动（Start）

### 2.1 标准命令（路径 A）

```bash
quantflow run \
  --mode paper \
  --strategy trend_following \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT \
  --timeframe 1h \
  --interval 60 \
  --capital 100000 \
  --config quantflow/config/paper_baseline0_overlay.yaml
```

### 2.2 启动瞬间验收

启动后 10 秒内在终端确认：

- [ ] 打印 `Starting paper trading`
- [ ] 打印 `Symbols: BTC/USDT, ETH/USDT, SOL/USDT`
- [ ] 打印 `Session started in paper mode`
- [ ] **没有** OKX 鉴权失败（paper 本地网关）
- [ ] 进程保持前台；`Ctrl+C` 为正常停止方式

可选：另开终端

```bash
quantflow status
```

- [ ] Version 为当前包版本；Phase 文案含 paper-first（若已部署 A4 改动）

---

## 3. 运行中（In-session）— 每班 / 每日

### 3.1 健康

- [ ] 进程仍在；无连续崩溃重启环
- [ ] 数据轮询无长时间 0 bar（网络/数据目录问题）
- [ ] 日志无 `Kill switch activated`（除非你手动测熔断）
- [ ] 无异常 `Fail-Closed` 冻结后仍持续开新仓（若有 pending 冻结，先停会话查对账）

### 3.2 Baseline-0 行为信号（观察项，非硬阈值）

- [ ] 三币均可能出现信号/持仓（允许某币阶段性空仓）
- [ ] 约每 48 根**对齐时间戳**后，日志可出现 symbol rebalance / 权重变化（`s5 symbol rebalance` 一类）
- [ ] 费率路径：paper 成交应带 fee 语义（与 0.1% 合同一致；勿用 0 费幻象解读收益）

### 3.3 禁止项（红线）

- [ ] **禁止**把本次会话改成 `--mode live` / `sandbox` 却仍宣称 Baseline-0
- [ ] **禁止**为“提高收益”临时关掉 fee/slip 或关掉 RP 却不改 baseline id
- [ ] **禁止**用 silo `risk_parity` 脚本收益对比本会话 shared-book 权益
- [ ] **禁止**对运行中会话做全宇宙 Optuna 热更新参数

---

## 4. 停止（Stop）

- [ ] `Ctrl+C` 优雅退出
- [ ] 确认终端出现 stopping / 无半截 traceback 卡死
- [ ] 若启用了 checkpoint（`state.checkpoint` 类配置为 on）：记录 checkpoint 目录是否有新快照（可选）

---

## 5. 停止后（Post）— 当日收工

### 5.1 必做

- [ ] 记下：启动时间、停止时间、是否异常退出
- [ ] 若做了研究对比：注明本次是 **路径 A（无 nested）** 还是 **路径 B（有 nested）**
- [ ] 收益解读：单日 paper PnL **不得**直接当作 WFO OOS 或生产 alpha

### 5.2 与候选卡对齐（按需，建议每周 1 次）

```bash
python scripts/run_baseline0.py
# 或仅 WFO：
python scripts/run_baseline0.py --skip-full
```

- [ ] 打开 `data/paper_replay/baseline0/gate.json`
- [ ] `decision` 仍为 `PAPER-GO` 的五项 checks 仍为 true  
  （若变 NO-GO：停日常扩容，先走 Wave C 升级规则，而不是调参硬扛）

### 5.3 回归冒烟（改代码后）

```bash
python -m pytest tests/unit/test_paper_replay.py tests/unit/test_state_store.py -q
python scripts/preflight_baseline0_paper.py
```

---

## 6. 故障速查

| 现象 | 优先检查 |
|------|----------|
| `No data` / 0 bars | `data/parquet`、download、timeframe=1h |
| 只有单币在动 | 是否漏了 `--symbols` 三币 |
| 完全无 rebalance 日志 | overlay 是否真的加载；`enabled/level/rebalance_every_n_bars` |
| 行为与 `gate.json` 差很多 | 是否在用路径 A 对比路径 B；nested 门差异 |
| 想“更真”的方向门 | 用 `paper_replay` / `run_baseline0.py`，或单独立项把 gate 接到 CLI（当前未交付） |
| 误触 live | 立刻停；检查 mode 与 env；本清单不授权 live |

---

## 7. 一页口令（复制区）

```text
【Baseline-0 Paper 日课】
1) python scripts/preflight_baseline0_paper.py
2) quantflow run --mode paper --strategy trend_following \
     --symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframe 1h --interval 60 \
     --capital 100000 --config quantflow/config/paper_baseline0_overlay.yaml
3) 确认 Symbols 三币 + paper mode
4) 运行中：禁 live / 禁改费滑 / 禁 silo 对比
5) Ctrl+C 停止；必要时 python scripts/run_baseline0.py 复核 gate.json
```

---

## 8. 相关文件

| 文件 | 角色 |
|------|------|
| `docs/research/Candidate-Baseline-0.md` | 实验合同 |
| `docs/research/Candidate-Baseline-0-results.md` | PAPER-GO 数字 |
| `docs/research/Wave-C-ab-verdict.md` | 为何仍用 classic/1h |
| `quantflow/config/paper_baseline0_overlay.yaml` | 日常 run 配置 |
| `scripts/run_baseline0.py` | 研究复现 |
| `scripts/preflight_baseline0_paper.py` | 启动前自动检查 |
