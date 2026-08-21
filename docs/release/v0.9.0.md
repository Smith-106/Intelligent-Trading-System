# QuantFlow v0.9.0

发布日期：2026-08-21

## 亮点

**多交易所历史数据接入 + 交易所后缀分区隔离。**
OKX（主源）+ Binance 公共归档 + Bybit V5 三所统一管道；物理分区按交易所后缀隔离，读侧解析层自动优先干净源。不换引擎；不改 B0/B3–B5 冻结；`promotion_eligible` 恒 false；parity 仅 paper↔live。

### 多交易所接入（本版本核心）

| 交易所 | 命令 | 数据 | 分区 |
|--------|------|------|------|
| OKX（主源） | `download --symbols ...` / `download-funding` / `download-oi` | K 线批量 + funding/OI 元数据 | `*-OKX` |
| Binance 归档 | `download-binance` | 月度 CSV（免鉴权无限频），spot/futures | `*-BINANCE` |
| Bybit V5 | `download-bybit` / `download-bybit-funding` / `download-bybit-oi` | K 线（含交割合约）+ funding/OI（mark-price 折算 USD） | `*-BYBIT` |

- **三模型共识设计**：deepseek-v4-flash + GLM/ox-alpha-free + hy3 全维度交叉共识（P1 接入设计 → P2 元数据 → P3 futures/USD 折算/OKX 后缀 → P4 生产迁移/web 迁移）
- **实测验证**：Bybit funding 90 行/OI 168 行、OI USD 折算 72/72 行命中（偏差 0.51% < 2% 验收线）、futures kline 端到端落盘
- **交割合约映射**：`BTC/USDT:USDT-260904` → 原生 V5 id `BTCUSDT-04SEP26`（DDMMMYY 格式实测发现并修正；20 字符 validator 零改动）

### 读侧解析层（架构决策）

- `DataStore.resolve_symbol()`：显式优先级链 `(-OKX, -BINANCE, bare)`——web 读路径自动消费干净源；无任何后缀分区时零行为变化
- **否决透明 fallback**（三模型一致）：防混源静默污染回测输入；provenance 经日志显式外露
- web 写侧同步对齐：station 下载落 `-OKX`；tag/查询复用同一 resolver

### 生产数据迁移

- **Binance 存量全量重跑**至 `-BINANCE` 分区：BTC(1d+1h)/ETH/SOL/XRP(1h) 共 5 组 ≈ 207k bars
- **奇偶校验全过**：新旧重叠率 100%、close 中位偏差 0.008–0.013%（容忍带 1%）
- **时间戳单位修复**：Binance archive 近期月份 `openTime` 由毫秒改微秒 → `_normalize_epoch_ms()` 幅值判别自适应（否则"未来数据泄漏"误报）
- **迁移工具**：`scripts/archive_legacy_partitions.py` —— dry-run 默认 / 显式映射表 / 归档目的地在 parquet_dir 外（防 list_symbols 污染）/ `--relabel-meta-okx` 保住不可再生的纯 OKX 元数据历史
- 顺序铁律：重跑 → 校验 → 切读取方 → 归档（归档留用户 `--apply` 决策）

### 兼容性

- 无后缀旧分区继续可读（resolver bare 兜底）；CLI 全部新参数均有安全默认值
- 后缀永不进入 ccxt/gateway 路径（交易符号语义不变）
