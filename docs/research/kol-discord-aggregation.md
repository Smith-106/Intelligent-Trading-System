# Discord KOL 带单 / TradingView 图聚合（辅助交易）

**Status**: MVP scaffold（2026-08-10）  
**定位**: **顾问式**信号聚合 + 审计落盘，**默认不自动跟单**  
**与产品定位关系**: 非 SaaS copy-trading；不替代 B0 / vs-BTC 产品门；可作 **overlay 输入** 或人工辅助

---

## 1. 你要的能力 vs 本轮交付

| 需求 | 交付 | 限制 |
|------|------|------|
| 聚合 Discord 群内几十个 KOL | 注册表 `kol_registry.yaml` + 多 channel poll/export | 需你自己填 channel_id / 权重 |
| 带单文本（多空/进出场） | 中英正则解析器 `parse_trade_text` | 口语乱码/黑话需迭代规则 |
| TradingView 截图多 | 附件下载 + chart 启发式 + **可选 OCR** | OCR 依赖本机 tesseract；默认可不装 |
| 辅助交易 | 时间窗 **共识**（多源加权） | **不**直连下单；`auto_trade: false` |
| 挂单/趋势分析混杂 | confidence 降权 + 共识门槛 `min_sources` | 噪音源请降低 `weight` 或 disable |

---

## 2. 架构

```text
Discord channels (KOL posts + TV images)
        │
        ├─ export JSON  (DiscordChatExporter / 自备 dump)
        └─ bot REST poll (DISCORD_BOT_TOKEN)
                │
                ▼
        message_to_signal()
          · text parser (side/symbol/SL/TP/tf)
          · attachments → chart_ocr (optional)
                │
                ▼
        data/kol_signals/signals.jsonl   (audit)
                │
                ▼
        aggregate_consensus(window, min_sources, min_score)
                │
                ▼
        latest_consensus.json  → 人工 / 未来 paper overlay
```

**安全默认**:

- 不写 API Key 进仓库；只用 `DISCORD_BOT_TOKEN` 环境变量  
- 不自动 `send_order`  
- 共识 `actionable` 只是「多源同意」，**不是** GO 晋级  

---

## 3. 快速开始

### 3.1 配置 KOL 表

编辑 [`quantflow/config/kol_registry.yaml`](../../quantflow/config/kol_registry.yaml)：

```yaml
sources:
  - source_id: kol_alpha
    display_name: "Alpha"
    platform: discord
    channel_ids: ["你的频道雪花ID"]
    weight: 1.2
    enabled: true
```

Discord：设置 → 高级 → 开发者模式 → 右键频道复制 ID。

### 3.2 离线导入（推荐先跑通）

用 [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) 导出 JSON：

```bash
export PYTHONUTF8=1
python scripts/kol_discord_ingest.py export path/to/channel.json --images --ocr auto
# 或
quantflow kol-ingest export --path path/to/channel.json --images --ocr auto
```

### 3.3 Bot 轮询（持续）

1. Discord Developer Portal 建 Bot，邀请进服务器，勾选读消息历史  
2. `export DISCORD_BOT_TOKEN=...`（Windows: `$env:DISCORD_BOT_TOKEN=...`）  
3.

```bash
python scripts/kol_discord_ingest.py poll --limit 50 --images --ocr auto
quantflow kol-ingest poll --channel 1234567890 --images
```

### 3.4 共识

```bash
python scripts/kol_discord_ingest.py consensus --window-hours 6 --min-sources 2
# → data/kol_signals/latest_consensus.json
```

`actionable: true` 表示：窗口内 ≥`min_sources` 个源、方向一致且加权分数够。

---

## 4. TradingView 图怎么处理

| 步骤 | 行为 |
|------|------|
| 识别 | 文件名/URL 含 tradingview/chart/cdn.discord… → `is_chart_likely` |
| 下载 | `data/kol_signals/attachments/`（gitignore） |
| OCR | `auto`：有 pytesseract+Pillow 则抽字；否则空文本 |
| 合并 | OCR 文本并入 `parse_trade_text` 再提 symbol/side/levels |

**未装 OCR 时**：仍可聚合**文字带单**；纯图策略帖 confidence 会低，需装 Tesseract 或后续接视觉 API（`vision_stub` 钩子已留）。

可选安装：

```bash
pip install pytesseract Pillow
# 并安装系统 Tesseract-OCR
```

---

## 5. 模块路径

| 模块 | 路径 |
|------|------|
| 包 | `quantflow/strategy/kol_signals/` |
| 注册表 | `quantflow/config/kol_registry.yaml` |
| 脚本 | `scripts/kol_discord_ingest.py` |
| CLI | `quantflow kol-ingest` |
| 单测 | `tests/unit/test_kol_signals.py` |
| 运行时数据 | `data/kol_signals/`（不入库） |

---

## 6. 明确不做（本 MVP）

- 自动跟单 / 一键复制仓位  
- 保证解析 100% 口语/黑话  
- 云端多用户 SaaS  
- 用 KOL 共识绕过 validation_gate / paper 门槛  
- 把 KOL 胜率吹成已验证 alpha（需独立 track record 合同）  

---

## 7. 建议演进（有数据后再做）

1. 每源 **hit-rate / 滞后 / 回撤** 账本 → 动态降权  
2. 视觉模型读 TV 图（价位框、趋势线）替换弱 OCR  
3. 共识 → **paper-only overlay** 合同（强制 vs BTC + 成本）  
4. 与 `BookRiskBudget` sleeve=`overlay` 对齐仓位帽  

---

## 8. 一句话

> **先把几十个 KOL 的文字+TV 图变成可审计的结构化信号与多源共识；默认只辅助决策，不自动跟单。**
