# 付费成员：管理员不给 Bot 时如何「尽量实时」同步 KOL

**结论先说**  
Discord **不会**给普通成员一个合法的「用户 Token 常驻爬群 API」。  
管理员不邀请 Bot 时，**无法**用 QuantFlow 的 `poll`（Bot REST）做真实时。  
你能做的是下面三档，按推荐顺序选。

---

## 0. 现实分层

| 档位 | 延迟 | 是否要管理员 | 合规性 | 推荐 |
|------|------|--------------|--------|------|
| **A. 官方 Bot / 转发到你的服** | 秒级 | **要** | 好 | ⭐ 最好，但你说可能拿不到 |
| **B. 定时导出 + 自动 ingest** | **1～5 分钟** 准实时 | 不要 | 相对稳妥* | ⭐ 成员默认方案 |
| **C. 只同步「高信号」人工/半自动** | 你看到再贴 | 不要 | 最好 | 适合带单精选 |
| **D. 用户 Token 自机器人常驻** | 秒级 | 不要 | **违 ToS，易封号** | ❌ 不做 |

\*「导出工具用你自己的登录会话读你有权看的频道」仍须遵守群规与 Discord 条款；**不要**把 Token 写进仓库/聊天，**不要**二次公开付费内容。

---

## 1. 为什么「成员」做不到官方实时

```text
Discord 读消息的正规方式 = Bot 已被邀请进该服务器
        +
   Bot Token + 频道权限（读历史）
```

你只有会员身份时：

- 不能自己把 Bot 拉进 **Kolunite** 这类付费服  
- 用户账号自动化（self-bot）= 平台明确禁止  
- 所以 QuantFlow `kol-ingest poll` **对你当前权限不适用**

---

## 2. 推荐方案 B：准实时「导出环」（1～5 分钟）

对交易辅助参考权重，**1～5 分钟延迟通常够用**（KOL 打字/截图本身也不是毫秒行情）。

### 流水线

```text
[你的会员账号能看见的频道]
        │  每 N 分钟
        ▼
DiscordChatExporter（或同类，本机会话）
  → data/kol_exports/<channel>.json (+ 附件可选)
        │
        ▼
python scripts/kol_discord_ingest.py export ... --images --ocr auto
        │  message_id 去重，重复跑安全
        ▼
python scripts/kol_discord_ingest.py consensus
        │
        ▼
data/kol_signals/latest_consensus.json
        │
        ├─ reference 命令 → 看市场评估/权重
        └─ kol_reference.enabled → paper 仓位微调（不跟单）
```

### Windows 任务计划（思路）

1. 固定目录：`data/kol_exports/`  
2. 任务 A（每 2～5 分钟）：只导出**带单/持仓/信号**相关频道（不要一次导出学习视频区）  
3. 任务 B（紧接 A 或同一脚本后半段）：

```powershell
$env:PYTHONUTF8 = "1"
cd "C:\Users\niko\Desktop\智能交易系统"

# 对每个导出文件（示例）
Get-ChildItem .\data\kol_exports\*.json | ForEach-Object {
  python .\scripts\kol_discord_ingest.py export $_.FullName --images --ocr auto
}
python .\scripts\kol_discord_ingest.py consensus --window-hours 6 --min-sources 2
python .\scripts\kol_discord_ingest.py reference --system-side BTC/USDT=long
```

4. 电脑休眠则断更 → 可挂一台常开小主机 / 云主机（**仍是你的会员会话与导出，不是 self-bot 服务化爬群**）。

### 延迟怎么选

| 间隔 | 体验 | 注意 |
|------|------|------|
| 1 分钟 | 接近「实时带单」 | 导出工具/Discord 限速、机器耗电 |
| 2～5 分钟 | **性价比最高** | 参考权重场景足够 |
| 15～60 分钟 | 偏复盘 | 不适合「刚喊单就加权重」 |

### 频道怎么挑（结合 Kolunite 表）

优先高频导出（带单/信号）：

- 社区指标（BTC/ETH 信号）  
- 陈哥合约、罗晟开单、三马哥、WWG 操作提醒/持仓  
- illusion / 部分英文低倍合约源  

低频或降权：

- 纯教学视频、新闻长文、测试区  
- 赌狗/高噪声源 → registry `weight` 低或关闭  

---

## 3. 方案 A：仍值得要管理员做的「真实时」（一句话怎么要）

不用要「管理权」，只要其一：

1. **只读 Bot**：你们加一个只能读指定信号频道的 Bot，Token 只在你本机  
2. **Webhook / 转发**：信号频道 → 转发到 **你自己的 Discord 服务器**，你在自己服上跑 Bot `poll`  
3. **官方镜像**：若社群有 Telegram/邮件/App 推送，对**开放 API 的渠道**再接（比硬爬 Discord 干净）

话术示例：

> 我只做个人研究机上的多源共识与仓位参考，不二次分发。能否提供只读 Bot 或把信号频道转发到我自有服务器？

---

## 4. 方案 C：半自动「高信号实时」

适合你人在看盘时：

1. 手机/桌面 Discord 通知打开 **关键信号频道**  
2. 重要单复制到本机 `data/kol_exports/manual.json`（最小消息结构见主文档）  
3. 跑一次 `export` + `consensus`  

延迟 = 你的反应时间；噪声最低。可与方案 B 并行：B 打底，C 补刀。

---

## 5. 明确不要做的

| 做法 | 原因 |
|------|------|
| 用户 Token 写入 QuantFlow / 常驻脚本爬群 | 违 Discord ToS，封号丢会员 |
| 把付费频道内容公开/转卖 | 群规与权利风险 |
| 期望毫秒级同步 KOL 图文 | 图文带单本身不是交易所行情；准实时足够 |
| 未开 `consensus` 就 `kol_reference.enabled` | 空文件/过期 → 权重恒为 1.0 或误用旧数据 |

---

## 6. 和「参考权重」目标的匹配

你的目标是 **市场评估 + 带单 → 参考权重**，不是 HFT 跟单：

| 需求 | 1～5 分钟导出环 | 真 Bot 实时 |
|------|-----------------|-------------|
| 多空共识温度 | ✅ | ✅ |
| 仓位 ±15%/−25% | ✅ | ✅ |
| 抢 KOL 同一秒入场 | ❌（也不建议） | 仍受解析/OCR 拖累 |

**产品建议**：把「实时」定义成 **「共识窗口内持续更新的参考权重」**（例如 6h 窗 + 每 2 分钟刷新），而不是「逐条跟单」。

---

## 7. 最小落地清单（管理员不给 Bot）

1. [ ] `kol_registry.yaml` 填好你**买到的档位**能看的源（先 5～10 个高热度带单源）  
2. [ ] DiscordChatExporter 对本机登录，导出这些频道 JSON  
3. [ ] 计划任务每 2～5 分钟：export → consensus →（可选）reference  
4. [ ] paper 验证几天后再 `kol_reference.enabled: true`  
5. [ ] 仍抽空要一次「只读转发」——有则升级到真实时  

---

## 8. smart-search 调研：有没有「无需管理员」的真实时？（2026-08）

### 8.1 官方结论（权威）

Discord 帮助中心 [Automated User Accounts (Self-Bots)](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)：

> 自动化应使用 **bot account**；**Automating normal user accounts (self-bots) is forbidden**，发现可 **account termination**。

因此：**不存在「官方认可 + 无需管理员 + 用户账号 WebSocket 实时」的方案。**

### 8.2 网上实际出现的「无管理员实时」类别

| 类别 | 代表 | 要管理员？ | 真实时？ | 合规 | QuantFlow 态度 |
|------|------|------------|----------|------|----------------|
| **Self-bot / 用户 Token 常驻** | YouTube 教程、[discord-selfbot crate](https://lib.rs/crates/discord-selfbot) 等 | 否 | 是（Gateway） | **违 ToS**，作者自述可封号 | **不实现、不接入** |
| **转发 SaaS / 跨服 Bot** | ForwardMsg、开源 Message-Forwarder 等 | **是**（源服要装 Bot） | 是 | 正规 Bot API 可合规 | 需管理员；装好后可 `poll` |
| **DiscordChatExporter** | [Tyrrrz/DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) | 否（用户可读频道） | **否**，快照导出 | 用户 Token 自动化 **违 ToS**（项目 README 亦警告） | 仅作 **人工/低频** 导出入口；**不**内置用户 Token 轮询 |
| **增量备份包装** | [DiscordChatExporter-incrementalBackup](https://github.com/slatinsky/DiscordChatExporter-incrementalBackup) | 否 | **准实时轮询**（分钟级） | 同上，依赖用户 Token | 可选外部工具；风险自担 |
| **浏览器扩展一次性导出** | ExportComments 等 | 否 | 否 | 偏手动会话 | 偶发补数 |

### 8.3 调研结论（直接回答）

1. **没有** 同时满足：无需管理员 + 官方合规 + 秒级实时 的公开方案。  
2. 网上「无管理员实时」几乎都是 **self-bot** → 与官方禁令冲突；QuantFlow **不会**加用户 Token `poll`。  
3. **最接近且仍属成员可做的**：外部 **DCE / 增量导出 每 2～5 分钟** → 本仓库 `export` + `consensus`（见 §2 与 `scripts/kol_near_realtime_tick.ps1`）。  
4. **唯一合规秒级**：管理员只读 Bot 或转发到你自有服（§3）。  
5. 转发类产品（Discord↔TG 等）写的是 **Bot 进源服**，**不能**替代「管理员不给权限」。

### 8.4 证据链接

- Discord 官方 self-bot 禁令：https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots  
- DiscordChatExporter：https://github.com/Tyrrrz/DiscordChatExporter  
- 增量导出包装：https://github.com/slatinsky/DiscordChatExporter-incrementalBackup  
- Self-bot 库自述违 ToS：https://lib.rs/crates/discord-selfbot  
- 转发需 Bot/权限的行业文（需源服装 Bot）：检索示例 ForwardMsg / Discord-Message-Forwarder 类产品说明  

---

## 9. 一句话

> **调研结果：无管理员时没有合规真实时；要么 self-bot（封号风险，本项目不做），要么 2～5 分钟导出准实时，要么继续要管理员开只读/转发。**
