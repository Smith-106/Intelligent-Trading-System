# 产品简报 (Product Brief)

## 项目名称
QuantFlow — 个人 Crypto 量化交易系统

## 一句话定位
面向个人/小团队的 Crypto 量化交易系统（OKX），覆盖策略研究→回测验证→模拟盘→小资金实盘的完整闭环，内置前沿防过拟合体系和模块化六层架构。

## 目标用户
- 常驻海外（日本）的个人量化交易开发者
- 使用 OKX 交易所进行 Crypto 实盘交易
- 希望从规则型策略起步，逐步扩展到 AI 辅助分析
- 开发偏好：开源优先、大模型辅助开发、架构先行

## 核心问题
传统量化系统要么是"只能回测的玩具"，要么是"机构级复杂系统"，缺乏适合个人的可运行、可验证、可维护的完整链路。

## 解决方案
QuantFlow 提供：
1. **双引擎研发流程**：VectorBT（向量化极速研究） + 事件驱动引擎（精确验证+实盘）
2. **前沿防过拟合体系**：CPCV + DSR + PBO + WFO + GO/NO-GO 决策门
3. **OKX 实盘对接**：CCXT + OKX API，7×24 开放市场，小额即可验证
4. **DuckDB+Parquet 数据层**：Quant 2.0 Feature Store，研究+实盘一致性
5. **模块化六层架构**：架构先行，接口定义清晰，便于迭代扩展
6. **完整交易会话**：TradingSession 统一 backtest/paper/live 模式

## 核心差异化
| 维度 | QuantFlow | 传统个人量化 | 机构系统 |
|------|-----------|------------|---------|
| 防过拟合 | CPCV+DSR+PBO (前沿) | WFO 或无验证 | 专业级但门槛高 |
| 回测-实盘一致性 | TradingSession 统一引擎 | 通常不一致 | 专用引擎 |
| 数据一致性 | DuckDB Feature Store | SQLite 或 CSV | 专业 Feature Store |
| 实盘验证 | OKX (24h, API开放) | A股(门槛高, T+1) | 多市场 |
| 开发效率 | AI辅助+开源框架 | 纯手工 | 团队协作 |

## 商业模式
- 非商业项目，个人量化研发工具
- 目标：实盘产生正向收益，验证系统可靠性
- 长期：构建"AI辅助量化研发工作流"

## 成功指标
- Phase 1：单策略回测年化夏普 > 1.0，CPCV PBO < 0.5 ✅ 已验证（Sharpe=2.27, PBO=0.267）
- Phase 2：模拟盘运行 ≥30 天，与回测偏差 < 10% ✅ 框架就绪
- Phase 3：小资金实盘运行 ≥90 天，最大回撤 < 15% ✅ 框架就绪

## 关键约束
- 不追求高频交易（低频/中低频）
- 不追求微秒级延迟
- 单机部署（Docker Compose），不需要分布式
- 开发者常驻日本，使用 OKX（Crypto 单市场，后续可扩展A股）
- Phase 1 命令行界面，Phase 2 引入 Web UI
- Python 3.11+，依赖尽量轻量

## 技术栈概览
- 语言：Python 3.11+
- 回测研究：VectorBT + Optuna
- 事件驱动验证/实盘：自建引擎 + PaperGateway/OKXGateway
- 实盘接口：CCXT + OKX API
- 数据存储：DuckDB + Parquet (Hive分区)
- 数据源：CCXT (Crypto) + AKShare/Tushare (研究参考)
- 指标库：pandas-ta + TA-Lib
- 防过拟合：CPCV + DSR + PBO + WFO (purgedcv)
- 风控：半Kelly + VaR/CVaR + 回撤熔断 + Kill Switch
- 监控：Grafana + Prometheus + Telegram/LINE
- 容器：Docker + Docker Compose
- ML(V3)：AIFactorEngine + Meta-Labeling + FinBERT