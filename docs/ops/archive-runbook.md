# 旧混合分区归档 Runbook（P5 三模型共识版）

> 适用：`scripts/archive_legacy_partitions.py`（F1/F3 修复后版本）
> 铁律：**重跑 → 校验 → 切读取方 → 归档**，顺序不可交换。
> 归档 = rename 非删除；回滚参照 `manifest_<stamp>.json`。

## 当前盘面（2026-08-21）

| 分区 | 状态 |
|---|---|
| `BTC_USDT-BINANCE` / `ETH_USDT-BINANCE` / `SOL_USDT-BINANCE` / `XRP_USDT-BINANCE` | ✅ 已就绪（v0.9.0 重跑，奇偶校验过：重叠率 100%、close 中位偏差 ≤0.013%） |
| `-OKX` 分区 | ⏳ 待 OKX 网络恢复后重跑（本机 DNS 不可达） |
| `BTC_USDT` 等 4 个裸分区 | 归档目标 |
| `meta_funding_rate/BTC_USDT`、`meta_open_interest/BTC_USDT` | **纯 OKX 数据，funding 仅 ~90 天可再生 → 必须 relabel 保住，不可归档** |
| `BTC-USDT-SWAP` | 显式排除，勿动（永续数据集专名，非命名事故） |

## 执行步骤

```bash
# ① dry-run 核对计划（应见：4 个 OHLCV move + 2 个 meta relabel，无 BLOCKED、无交叉）
python scripts/archive_legacy_partitions.py --relabel-meta-okx

# ② 停写入方（防 Windows 文件锁）：paper session / web station / 后台下载

# ③ 执行（rename 非删除；manifest 先写后执行，中途崩溃可回放）
python scripts/archive_legacy_partitions.py --relabel-meta-okx --apply

# ④ 验收
#    - data/parquet 下裸分区消失，仅剩 *-BINANCE / BTC-USDT-SWAP / meta_*(-OKX)
#    - manifest_<stamp>.json status=applied 且与移动一一对应
#    - 特征冒烟：compute_features("BTC/USDT") 的 funding/OI 列非全 NaN
#      （store._query_meta 已支持 -OKX→-BINANCE→bare 回退 + WARNING）

# 回滚（如需）：按 manifest 将 moves/relabels 逐条反向执行
```

## OKX 重跑待办（网络恢复后）

```bash
# 前置门探测
python -c "import socket; socket.getaddrinfo('www.okx.com', 443)"

# OHLCV（默认落 -OKX；与 relabel 目标同名，keep=last 幂等续写无缝衔接）
quantflow download --symbols BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT --timeframe 1h --start 2019-01-01
quantflow download --symbols BTC/USDT --timeframe 1d --start 2019-01-01

# meta（~90 天窗口滚动回补；失败批次 exit 1 可驱动自动化重试）
quantflow download-funding --symbol BTC/USDT --days 90
quantflow download-oi --symbol BTC/USDT --days 180 --period 1H
```

## CI 门禁清理状态（P5 Phase0 完成 / G3-G5 待专项）

已完成：opentelemetry mypy override（确定性 CI blocker）、dev 工具钉版
（ruff/mypy/pip-audit `==`）、归档脚本 F1/F3 修复、meta 读回退 F2、CLI 退出码 F5。

待专项（需 Py3.11 权威环境，本机仅有 3.14.6 且无 uv/py-3.11）：
Mypy ~420 处分层清零（operator/unused-ignore 真修、arg-type 分流、type-arg 定向豁免，
只减不增守卫）；锁文件在 3.11 重生成；pip-audit 双面审计（本地 UTF-8 实测当前锁无 CVE）。
