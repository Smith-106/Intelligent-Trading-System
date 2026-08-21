# 市场历史数据源研究：三模型共识 + 实测验证

**Date**: 2026-08-20
**Method**: 三模型共识式深度协作（deepseek-v4-flash / GLM-5.2-fast / hy3 各自独立研究全部维度 → root 交叉共识）+ 实测验证（curl HTTP 状态 + 数据内容检查）
**Scope**: 可获取的丰富市场历史数据源（OKX / TradingView / Binance / Bybit / Kraken / 中文生态 / tick 级平台）

---

## 0. 一句话结论

| 问题 | 结论 |
|------|------|
| 最丰富且可获取的数据源？ | **Binance 官方 Archive（data.binance.vision）**——免费、无 key、2017 起全历史 1m 全量 + funding 归档，三模型全票 P0，实测 HTTP 200 且 CSV 内容正确。 |
| 成本最低的扩展路径？ | **OKX 现有管道扩展**——QuantFlow 已有 CCXT fetcher + 300-bar 分页 + funding/OI CLI，零改造衔接。 |
| TradingView 值得用吗？ | **分歧**：GLM 认为可作跨市场补充（P1），hy3 认为 ToS/CAPTCHA 风险高（P3）。共识：仅作补充验证源，不作主数据源。 |

---

## 1. 三模型共识 Top-5 数据源

### 🥇 P0 · Binance Public Data Archive（3/3 全票）
- **URL**: https://data.binance.vision/
- **历史深度**: 现货 2017-08-17 起、U 本位合约 2019-09-08 起；daily/monthly 全量文件，1s/1m/5m/…/1M 全频率
- **获取方式**: 批量 ZIP 下载（无 key、无限流）
- **字段**: klines（OHLCV+taker buy vol 12 字段）、trades、aggTrades、fundingRate、markPrice、indexPriceKlines、metrics
- **集成难度**: ⭐ 低——下载→解压→现有 Parquet Hive store 入库，无分页/限流
- **实测**: ✅ HTTP 200（1d/1m/fundingRate 全部可下载，CSV 内容验证正确）

### 🥈 P0 · OKX API 扩展（3/3 全票）
- **URL**: https://www.okx.com/docs-v5/
- **历史深度**: 1m 约 2019 起、1D 更早；funding 全量、OI 历史（rubik 接口）
- **获取方式**: REST 分页（history-candles 300 根/页）；本地已有 CCXT fetcher 处理该上限
- **集成难度**: ⭐ 最低——已有 fetcher + download/download-funding/download-oi CLI + BTC 2019-2026 数据
- **实测**: ⚠️ 本环境 www.okx.com DNS 不通（网络问题，非 API 问题）；端点结构来自官方文档

### 🥉 P1 · Bybit V5 API（2/3 推荐）
- **URL**: https://bybit-exchange.github.io/docs/v5/market/kline
- **历史深度**: BTCUSDT perp 自 2018-12；1/3/5/15/30/60/120/240/360/720/D/W/M 全频率
- **获取方式**: REST `/v5/market/kline`（limit 1000/页 + start/end 游标）、funding history、OI；CCXT 支持
- **集成难度**: ⭐⭐ 低-中——分页模式与 OKX 类似可复用
- **实测**: ✅ HTTP 200，返回真实 K 线数据（BTCUSDT spot daily）

### P1 · Kraken OHLCVT 归档 + API（2/3 推荐）
- **URL**: https://api.kraken.com/0/public/OHLC
- **历史深度**: 从每个市场开始日起（BTCUSD 自 2013 起），1m-1440 全间隔
- **获取方式**: 免费 ZIP 归档下载 + REST API（720 根/请求）
- **字段**: OHLCVT（OHLCV + trades 计数）
- **集成难度**: ⭐⭐⭐ 中——归档 CSV 需解析
- **实测**: ✅ HTTP 200，返回真实 OHLCV 数据

### P2 · Tardis.dev（2/3 推荐，前瞻）
- **URL**: https://tardis.dev
- **历史深度**: tick 级 trades/orderbook 全历史（多数 2019 起），150+ 交易所
- **免费/付费**: 免费层 1M events/月；付费 $0.0015/trade
- **集成难度**: ⭐⭐⭐⭐ 中高——适合未来微观结构研究，当前 QuantFlow 以 OHLCV/funding/OI 为主

---

## 2. GLM 独有贡献：中文生态数据源

| 数据源 | 历史深度 | 免费/付费 | 优先级 | 理由 |
|---|---|---|---|---|
| **AKShare** 🇨🇳 | A股 1990-今 全频率 | 完全免费 | **P1** | 已在本地 `third_party/akshare`；一个 pip 包覆盖 A股/期货/基金/加密，中国市场唯一首选入口 |
| **Tushare Pro** 🇨🇳 | A股全历史 | 混合（积分制） | P1 | 数据质量优于 akshare（官方清洗），适合交叉验证 |
| **Baostock** 🇨🇳 | A股日/周/月 | 完全免费 | P2 | akshare 的免费备份源 |
| **MiniQMT** 🇨🇳 | tick 近1月/分钟近1年/日频20年 | 免费（需券商账户） | P2 | 兼做实盘交易通道 |

---

## 3. 实测验证结果（root 执行）

| 数据源 | 测试 | 结果 |
|---|---|---|
| Binance 1d K线 | `data/spot/monthly/klines/BTCUSDT/1d/2024-01.zip` | ✅ HTTP 200，CSV 12 字段正确（OHLCV+taker buy vol+quote vol+trade count） |
| Binance 1m 合约 | `data/futures/um/monthly/klines/BTCUSDT/1m/2024-01.zip` | ✅ HTTP 200（1.9MB） |
| Binance fundingRate | `data/futures/um/monthly/fundingRate/BTCUSDT/2024-01.zip` | ✅ HTTP 200 |
| Bybit K线 | `/v5/market/kline?category=spot&symbol=BTCUSDT&interval=D` | ✅ HTTP 200，retCode=0，真实数据 |
| Kraken OHLC | `/0/public/OHLC?pair=XBTUSD&interval=1440` | ✅ HTTP 200，真实数据 |
| OKX candles | `/api/v5/market/candles?instId=BTC-USDT` | ⚠️ 本环境 DNS 不通（网络问题） |

---

## 4. 建议获取命令（P0 优先）

```bash
# 1) Binance archive 全量 1m（BTCUSDT 2019-2026 按月下载）
for y in $(seq 2019 2026); do for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
  curl -sS -o /tmp/bn.zip "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-$y-$m.zip" \
  && unzip -o /tmp/bn.zip -d data/binance/um/1m/ && rm /tmp/bn.zip
done; done
# 同模式：fundingRate → data/futures/um/monthly/fundingRate/BTCUSDT/

# 2) OKX 扩展：复用现有 download CLI（quantflow/cli），加 --symbol/--bar 参数矩阵
# 3) Bybit：pybit 或 CCXT fetch_ohlcv 按 start/end 游标翻页（limit=1000），入库走现有 store
```

---

## 5. 风险提示（三模型共识）

1. **CryptoDataDownload** 免费 CSV 为非商业许可（CC BY-NC-SA 4.0）——商用受限
2. **CryptoCompare/CoinDesk Data** 免费层 2026-05-21 已退役——弃用
3. **TradingView 非官方库**（tvdatafeed/scraper）有 ToS/CAPTCHA/JWT 风险——仅作补充验证
4. **OKX 本环境 DNS 不通**——需在可访问网络环境验证（QuantFlow 生产环境已有 OKX 数据，说明实际可用）

---

## 6. 结论

**P0 双源** = Binance archive（全量免费下载，实测可用）+ OKX（现有管道零成本扩展）
**P1** = Bybit（交叉验证，实测可用）+ Kraken（2013 早期历史，实测可用）+ AKShare（中文生态，已在本地）
**P2** = Tardis.dev（未来微观结构研究）

**推荐行动**：优先接入 Binance archive（新增 `BinanceArchiveFetcher`：HTTP 下载→解压→解析 CSV→写 Parquet Hive 分区，复用现有 store 架构，预估 1-2 天），OKX 扩展多标的/多频率，AKShare 作为中国市场扩展入口。
