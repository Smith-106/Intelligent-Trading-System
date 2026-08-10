# T023 墙钟日历 — 再攒 ≥4 连续 UTC 日 Path A

**As-of UTC**: 2026-08-10  
**Ledger**: consecutive **3/7** · dates `2026-08-08` … `2026-08-10`  
**target_met**: **false**  
**Rule**: **每 UTC 日最多 1 credit**；**禁止**预写/回填 `2026-08-11`–`14`

---

## 1. 为什么 agent 不能“一次做完”

| 事实 | 含义 |
|------|------|
| 当前 UTC 日 = **2026-08-10** | 该日 **已 credit** |
| 7 日连续终点（从 08 起） | 需 **2026-08-14** 当日 Path A 成功 |
| 尚缺日期 | **08-11, 08-12, 08-13, 08-14**（**未来**） |

同一次对话/同一 UTC 日 **无法** 合法产生 4 个新 calendar credit。  
宣称 7/7 而 ledger 无对应日期 = **造假**，违反 T023/T016。

---

## 2. 目标轨迹（从现有 streak 延伸）

| UTC 日 | 动作 | 期望 consecutive |
|--------|------|------------------|
| 2026-08-08 | ✅ 已 credit | 1 |
| 2026-08-09 | ✅ 已 credit | 2 |
| 2026-08-10 | ✅ 已 credit | **3** |
| **2026-08-11** | 待跑 Path A + ingest | 4 |
| **2026-08-12** | 待跑 | 5 |
| **2026-08-13** | 待跑 | 6 |
| **2026-08-14** | 待跑 | **7 → target_met** |

若任一日漏跑 → 连续中断，需重新从新终点累计（工具按 ending-recent consecutive 计算）。

---

## 3. 每日最小命令（复制即用）

```bash
# 每个 UTC 日执行一次（建议 UTC 12:00 后或本地习惯固定点）
python scripts/paper_day_streak.py ingest --run-day-session
python scripts/paper_day_streak.py status --min-days 7
```

可选：真正挂起 paper 会话（非必须拿 credit，若 day-session 仅 preflight 路径已配置为可 credit）：

```bash
# 见 baseline0-paper-run-checklist Path A
# quantflow run --mode paper ...   # 仅当需要实盘纸面成交样本时
```

满 7 日后：

```bash
python scripts/paper_evidence_export.py dry-run --fills <真实成交数>
python scripts/paper_day_streak.py report --min-days 7
```

---

## 4. 验收（唯一合法 7/7）

```text
python scripts/paper_day_streak.py status --min-days 7
→ consecutive >= 7
→ target_met=true
→ credited_dates 含连续 7 个 UTC 日（当前轨迹下含 08-08…08-14）
```

---

## 5. 本文件完成语义

| 完成 | 未完成 |
|------|--------|
| 墙钟缺口与日历 **写清** | **4 个未来日的 credit** |
| 今日 3/7 **诚实冻结** | promote 真实过门槛 |
| 每日命令可复制 | 伪造 ledger |

*Wall-clock residual is calendar-bound; engineering cannot compress time.*
