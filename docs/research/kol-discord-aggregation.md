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

### 3.2 你只是付费成员时怎么连？（最重要）

| 身份 | 能否用 Bot `poll` | 推荐做法 |
|------|-------------------|----------|
| **群主 / 有管理权限** | 可以（邀请自己的 Bot） | `poll` 持续拉历史 |
| **付费成员 / 普通成员（你的情况）** | **通常不行** | **导出 JSON 再 `export` 导入** |
| 管理员愿意配合 | 让对方加 **只读 Bot** 或开 **转发 Webhook** | 再上 `poll` / 自定义 webhook |

**原因**: Discord Bot 必须被**邀请进该服务器**。付费群几乎都禁止成员乱拉 Bot；你没有「管理服务器 / 管理 Webhook」时，`DISCORD_BOT_TOKEN` 这条路对你**不可用**。

**不要做的事**:

- 用「用户 Token / 自机器人（self-bot）」挂账号自动爬群 → **违反 Discord ToS**，有封号风险；本项目**不支持、不接**用户 Token 自动化。
- 把群内容二次公开转卖/外泄 → 可能违群规与版权；仅限**个人研究机本地**使用。

---

### 3.3 成员可行路径 A — 官方客户端可读范围内的导出（推荐）

你的账号**本来就能看到**的频道，可以用桌面导出工具按**你自己的登录会话**导出（不是 Bot）：

1. 安装 [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter)（GUI 或 CLI）。  
2. 用**你的 Discord 账号登录导出器**（按工具说明；不要把 Token 写进仓库/聊天）。  
3. 选中付费群里你有权限的 **信号频道**（可多选 KOL 分频）。  
4. 格式选 **JSON**；若要 TV 图，打开 **下载附件 / media**。  
5. 导出到例如 `data/kol_exports/alpha-2026-08-10.json`（该目录可自建，导出物勿提交 Git）。

导入 QuantFlow：

```bash
export PYTHONUTF8=1
# 可选：先登记 source（channel_ids 填导出频道的雪花 ID）
# 编辑 quantflow/config/kol_registry.yaml → enabled: true

python scripts/kol_discord_ingest.py export data/kol_exports/alpha.json --images --ocr auto
python scripts/kol_discord_ingest.py consensus --window-hours 6 --min-sources 2
# 或
quantflow kol-ingest export --path data/kol_exports/alpha.json --images --ocr auto
quantflow kol-ingest consensus
```

**节奏建议（成员）**:

- 每日或每几小时 **手动/计划任务再导出一次**（增量靠我们 JSONL 按 message_id 去重，重复导出安全）。  
- Windows 可用任务计划程序跑：先调用导出 CLI，再跑上面的 `export` + `consensus`。  
- 多 KOL 多频道 = **每个频道一个 JSON**（或一次导出多个），`kol_registry.yaml` 里用不同 `source_id` + `weight`。

获取频道 ID：Discord 设置 → 高级 → 开发者模式 → 右键频道 → 复制 ID。

---

### 3.4 成员可行路径 B — 半自动（不破 ToS）

| 做法 | 说明 |
|------|------|
| **请求管理员** | 加一个**只读 Bot**（只读消息历史），Token 只放你本机 ENV；或官方 Webhook 转到你自己的服务器再采集 |
| **你自己的中转服** | 管理员允许的话，用频道关注/转发 Bot（需对方装）转到「你拥有的服务器」，再在你自己的服上跑 `poll` |
| **手动精选** | 重要单复制到本地 `manual.json`（同 export 结构）再导入 — 噪声低、适合先验证解析 |

手动 JSON 最小形状：

```json
{
  "channel_id": "123",
  "messages": [
    {
      "id": "msg1",
      "content": "LONG BTCUSDT entry 64000 SL 62000 TP 66000",
      "author": {"username": "kol_x"},
      "timestamp_ms": 1700000000000,
      "attachments": []
    }
  ]
}
```

---

### 3.5 Bot 轮询（仅当你能邀请 Bot 时）

1. Discord Developer Portal 建 Bot，**管理员**邀请进**该**服务器，勾选读消息历史  
2. `export DISCORD_BOT_TOKEN=...`（Windows: `$env:DISCORD_BOT_TOKEN=...`）  
3.

```bash
python scripts/kol_discord_ingest.py poll --limit 50 --images --ocr auto
quantflow kol-ingest poll --channel 1234567890 --images
```

付费成员若邀请失败（Missing Permissions）→ **回到 3.3 导出路径**，不要改用用户 Token。

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

## 8. 作为「参考权重」接入交易系统（你的目标）

你要的是：**市场评估 + 实时带单 → 参考权重**，不是跟单机器人。

```text
你的策略方向（trend / 风控后 signal）
        ×
KOL reference_multiplier  ∈ [1-max_cut, 1+max_boost]
        =
最终仓位名义（仍过 RiskEngine / max_position）
```

| 规则 | 行为 |
|------|------|
| KOL 与系统**同向** | 仓位略增（默认最多 **+15%**） |
| KOL 与系统**反向** | 仓位略减（默认最多 **−25%**） |
| 无共识 / 过期 / 未达 min_sources | **×1.0**（不掺和） |
| KOL 单独喊单、系统无方向 | **不开仓**（只写 assessment） |

### 配置（默认关）

`quantflow/config/default.yaml`：

```yaml
kol_reference:
  enabled: false   # 共识稳定后再 true
  max_boost: 0.15
  max_cut: 0.25
  consensus_path: "data/kol_signals/latest_consensus.json"
```

### 日常数据流（付费成员）

```bash
# 1) 导出/更新 KOL 消息 → 2) 共识 → 3) 看参考权重
python scripts/kol_discord_ingest.py export data/kol_exports/ch.json --images --ocr auto
python scripts/kol_discord_ingest.py consensus --window-hours 6 --min-sources 2
python scripts/kol_discord_ingest.py reference --system-side BTC/USDT=long,ETH/USDT=long
```

`reference` 输出：

- `market_assessment.label`: risk-on / risk-off / mixed / neutral  
- `symbols.*.multiplier`: 给你的系统方向用的仓位系数  
- **不会**调用下单 API  

开启 `kol_reference.enabled: true` 后，`TradingSession` 在 `PositionSizer.size(..., reference_multiplier=…)` 自动乘上该系数。

---

## 9. 一句话

> **KOL 只提供市场评估与带单共识权重：同向略加仓、反向略减仓；系统策略仍是唯一方向源，默认不跟单。**
