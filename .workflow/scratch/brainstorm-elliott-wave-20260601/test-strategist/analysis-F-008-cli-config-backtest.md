# F-008 — CLI elliott-wave命令 + elliott_wave.yaml配置 + VectorBT回测

> Role: test-strategist | Related decisions: TS-05, TS-10

## Architecture

CLI 命令、配置管理和 VectorBT 回测集成位于 L3 策略层和 CLI 入口层。测试架构 MUST 分为：

1. **CLI 层**：验证 Typer 命令的参数解析和执行
2. **配置层**：验证 elliott_wave.yaml 的加载和验证
3. **回测集成层**：验证 VectorBT 回测的端到端执行

测试模块位于 `tests/unit/cli/test_elliott_wave_cli.py` 和 `tests/integration/test_elliott_wave_backtest.py`。

## Interface Contract

CLI 和回测暴露以下测试接口：

- `cli_elliott_wave(mode: str, symbol: str, strategy: str, config: str) -> None` — CLI 入口
- `load_elliott_wave_config(config_path: str) -> ElliottWaveConfig` — 配置加载
- `validate_config(config: ElliottWaveConfig) -> ValidationResult` — 配置验证
- `run_backtest(strategy, data, config) -> BacktestResult` — VectorBT 回测执行

## Constraints (RFC 2119)

- CLI 命令 MUST 支持 `quantflow elliott-wave --mode backtest --symbol BTC/USDT` 格式
- 配置 MUST 从 elliott_wave.yaml 加载，优先级：CLI参数 > 环境变量 > YAML默认值
- 配置验证 MUST 检查参数范围（如 deviation 1-20、depth 3-50）
- VectorBT 回测 MUST 包含交易成本（手续费、滑点）
- 回测结果 MUST 输出 BacktestResult 结构（见 §2 Interfaces）
- 回测 MUST 标记 `@pytest.mark.slow`，不在快速测试套件中运行
- CLI 输出 MUST 使用 Rich 格式化，包含回测摘要表格

## Test Approach

### 单元测试

**CLI 命令测试**：
- 参数解析测试：验证所有 CLI 参数的正确解析
- 默认值测试：未指定参数时使用 YAML 默认值
- 错误参数测试：无效 symbol、不存在的 config 文件、非法 mode 值
- 使用 Typer 的 CliRunner 进行测试，不依赖实际命令行

**配置加载和验证测试**：
- 正确配置文件加载测试
- 缺失必填字段时的错误提示
- 参数范围越界时的错误提示
- 配置优先级测试：CLI参数覆盖YAML默认值

**elliott_wave.yaml 结构验证**：
```yaml
# 必填字段验证
strategy:
  name: "elliott_wave"          # MUST be "elliott_wave"
  zigzag:
    deviation: 5.0              # MUST be in range [1, 20]
    depth: 10                   # MUST be in range [3, 50]
    backstep: 2                 # MUST be in range [1, 20]
  fibonacci:
    retracement: [0.236, 0.382, 0.5, 0.618, 0.786]
    extension: [1.0, 1.272, 1.618, 2.0, 2.618]
  scaling:
    trial_pct: 0.10             # MUST be in [0.05, 0.20]
    add_pct: 0.25               # MUST be in [0.10, 0.40]
    chase_pct: 0.12             # MUST be in [0.05, 0.20]
    max_exposure: 0.60          # MUST be in [0.30, 0.80]
  risk:
    hard_stop_atr_multiple: 1.5
    soft_stop_atr_multiple: 2.5
    max_consecutive_losses: 3
```

### 集成测试

**VectorBT 回测端到端测试**：
- 完整回测流程：数据获取 → 策略初始化 → 信号生成 → 回测执行 → 结果输出
- 验证 BacktestResult 各字段的正确性
- 回测结果与手动计算的一致性验证

**防过拟合验证端到端测试**：
- CPCV 验证：6 组组合，统计通过率
- DSR 验证：计算修正夏普比
- PBO 验证：计算过拟合概率
- WFO 验证：5 窗口步进测试
- GO/NO-GO 门判定：全部通过输出 GO，任一不通过输出 NO-GO

**回归测试**：
- 现有 CLI 命令（download, research, optimize, validate, run, status）MUST 不受影响
- 现有测试套件 MUST 全部通过
- 新增 elliott-wave 命令不影响其他策略的回测

### 测试数据 Fixtures

```
fixtures/
├── config/
│   ├── elliott_wave_valid.yaml     # 有效配置
│   ├── elliott_wave_missing.yaml   # 缺失字段
│   ├── elliott_wave_invalid.yaml   # 非法参数
│   └── elliott_wave_minimal.yaml   # 最小配置
└── backtest/
    ├── btc_2020_2024_daily.parquet # 回测数据
    └── expected_results.json       # 预期回测结果
```

## TODOs

- [ ] 定义 CLI 命令的完整参数列表和帮助文本
- [ ] 确定 VectorBT 回测的手续率和滑点默认值
- [ ] 设计回归测试的自动化执行方案
- [ ] 参考 [F-004](analysis-F-004-elliott-wave-strategy.md) 确认回测验收标准
- [ ] 参考 [F-007](analysis-F-007-multi-timeframe-align.md) 确认多时间框架回测的数据需求
