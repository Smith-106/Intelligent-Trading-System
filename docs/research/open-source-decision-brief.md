# 开源决策简报（待你裁决）

> 状态：**决策材料，不是已执行公开。**  
> 私有远端现状：`Smith-106/Intelligent-Trading-System`（private）。  
> 可公开前工件：`docs/demo/` + `python scripts/demo_public_pack.py --check`。

## 1. 要回答的问题

**是否、以何种范围，把 QuantFlow 从「私有研究 OS」变成「可被第三人发现/复用的开源项目」？**

这与「细分能力最强」是**两条 KPI**：

| KPI | 是否需要开源 |
|-----|----------------|
| 验证门 + 成本保真 + paper 日课可复现（能力最强） | **否**（私有即可） |
| 生态 / stars / 社区策略资产（开源最强） | **是** |

## 2. 就绪度（工程侧）

| 项 | 状态 |
|----|------|
| 定位与非目标文案 | ✅ README + `docs/demo/POSITIONING.md` |
| 无密钥 demo 包 | ✅ `docs/demo/` + secret 扫描检查 |
| sample gate / fee×slip 结构 | ✅ 合成样例（非 alpha 宣称） |
| Path A/B 防误用 | ✅ CLI + checklist |
| P0 成本门 fail-closed | ✅ register 硬绑 |
| LICENSE 文件 | ❓ 开源前需选定 |
| 密钥/路径脱敏审计 | ⚠️ 开源前再扫一遍 `.env`、日志、data/ |
| 真实研究 gate.json 是否进公开仓 | ⚠️ 建议**不要**默认提交全窗 alpha 数字（防被当营销） |
| 是否接受 issue/PR 维护成本 | ❓ 产品决策 |

## 3. 方案对比

### 方案 A — **继续永私**（默认稳妥）

- **做**：能力迭代只服务本人/小团队；demo 包仅内部/朋友可见。
- **不做**：改 GitHub visibility、加 LICENSE、社区运营。
- **适合**：研究 OS 主线、不想维护 issue、策略细节敏感。
- **风险**：无外部审稿与生态；「开源最强」叙事永久不成立（可接受）。

### 方案 B — **docs / demo 先公开，core 仍私**（推荐过渡）

- **做**：单独 public 仓或 gist：`docs/demo` + 定位 + 架构图 + 无密钥脚本说明；core 仍 private。
- **不做**：放出完整策略参数、全窗 PnL、API 集成细节。
- **适合**：想建立公开叙事与反馈，但不想策略/执行细节被 fork。
- **风险**：文档与代码漂移；需声明「demo ≠ 可交易 alpha」。

### 方案 C — **core 开源（Apache-2.0 / MIT），研究产物默认不公开**

- **做**：`quantflow/` + tests + scripts（脱敏）public；`data/`、`.env`、真实 `gate.json` 结果 **gitignore**；README 强绑定非目标与 Path A/B。
- **不做**：承诺多所/SaaS；不把 Baseline 全窗收益当首页 KPI。
- **适合**：要可复现研究 OS、接受 PR、用社区补策略脚手架。
- **风险**：执行/风控细节被抄；维护成本上升；错误 KPI（stars）诱惑。

### 方案 D — **双仓：public core + private research**

- **做**：public 薄 core（接口 + paper + validation 骨架）；private 仓放策略参数、RD-Agent 密钥路径、真实报告。
- **适合**：长期既要生态又要 alpha 保密。
- **风险**：同步成本最高；需清晰 monorepo/subtree 策略。

## 4. 若选择开源：最低发布清单（门禁）

1. 选定 LICENSE（建议 MIT 或 Apache-2.0）。  
2. 全仓 secret 扫描（git history 含 API key → 先 rotate）。  
3. `data/`、`*.env`、真实 paper 会话、全窗结果 **不进 public**。  
4. README 首页保留：定位 / 非目标 / Path A·B / demo 入口。  
5. CI：`pytest` 核心 + `demo_public_pack.py --check` + `preflight`（有数据时）。  
6. 明确：公开仓 **不**以 stars 或名义 Sharpe 为成功标准。  
7. 首次 release tag 与 `docs/release/` 对齐。

## 5. 建议（可被否决）

在 **P0–P2 刚落地、全窗成本报告刚补齐** 的节点：

1. **短期（现在）**：选 **A 或 B**。  
   - 若完全不想外部噪音 → **A**。  
   - 若希望「研究 OS」叙事可被引用 → **B**（docs/demo 公开）。  
2. **中期（3–6 个月）**：paper 日课稳定 + ≥3 Baseline 合同可复现后，再评估 **C 或 D**。  
3. **永远不要**：用机构 KPI 或 stars 倒逼开源范围。

## 6. 决策记录（已裁决）

```text
日期: 2026-08-09
选择: B — docs/demo 先公开，core 仍 private
LICENSE（公开子集）: Apache-2.0
LICENSE（私有主仓）: 保持现有根目录 MIT（未在本决策中改为 Apache）
公开范围:
  - docs/public-demo/（定位、合成 gate、Apache LICENSE、PUBLISH 说明）
  - 可选：研究摘要 MD（不含 raw 全窗 JSON 亦可）
明确不公开:
  - quantflow/ 源码、data/、.env、真实 paper 会话、全窗原始 cost JSON（默认）
  - 主仓 Intelligent-Trading-System 保持 private
维护承诺:
  - 公开仓以文档为主；不承诺策略 PR
  - 不以 stars 为 KPI
工程落盘:
  - docs/public-demo/ + docs/research/open-source-decision-brief.md
  - 发布动作：由用户按 PUBLISH.md 手动 push（agent 不改 GitHub visibility）
复审日期: 2026-11-01 或 paper 日课稳定 + ≥3 Baseline 后再评估 C/D
```

### 与根目录 MIT 的关系

- **方案 B** 只授权「文档/demo 子集」用 **Apache-2.0**（`docs/public-demo/LICENSE`）。
- 私有主仓根 `LICENSE` 仍为 **MIT**，避免在未审计全仓依赖前整仓换协议。
- 若未来升到 **C（core 开源）**，再统一全仓 SPDX 与 NOTICE。
