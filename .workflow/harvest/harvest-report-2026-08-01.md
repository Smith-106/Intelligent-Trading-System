# Harvest Report — 2026-08-01

**执行者**: Qoder Agent  
**时间**: 2026-08-01  
**状态**: ✅ 完成

---

## 1. 源工件

| # | 工件 | 类型 | 日期 |
|---|------|------|------|
| 1 | `.workflow/scratch/20260731-retrospective-M4/retrospective.md` | 回顾 | 2026-07-31 |
| 2 | `.workflow/harvest/phase-6-final-report.md` | 完成报告 | 2026-07-31 |
| 3 | `.workflow/scratch/20260729-debug-odyssey-structlog-bridge/` | debug odyssey | 2026-07-29 |
| 4 | `.workflow/scratch/20260724-debug-odyssey-l6-sibling-sinks/` | debug odyssey | 2026-07-24 |
| 5 | `.workflow/scratch/20260724-improve-odyssey-strategy-engine-l6-decouple/` | improve odyssey | 2026-07-24 |
| 6 | `.workflow/scratch/20260723-improve-odyssey-trade-main-path/` | improve odyssey | 2026-07-23 |
| 7 | `.workflow/scratch/20260722-retrospective-security-hardening/` | 回顾 | 2026-07-22 |
| 8 | `.workflow/scratch/20260722-ui-odyssey-station-frontend/` | UI odyssey | 2026-07-22 |

---

## 2. 提取摘要

| 指标 | 数值 |
|------|------|
| 源工件数 | 8 |
| 初步提取候选片段 | ~25 |
| **去重过滤后新增片段** | **4** |
| 去重跳过（已有 knowhow） | 7 (F1-F7 M4 patterns) |
| 去重跳过（已有 spec） | 12 (L6 Protocol, timeout quadrant, flush_signals GIL, fail-silent, security insights ×7, UI specs ×4) |
| 去重跳过（已有 learnings） | 2 (Grep cache lag, metrics idempotent state) |
| 过滤（低价值/流程性） | ~5 (agent coordination, spec walkthrough) |

---

## 3. 路由结果

### 3.1 Knowhow 新增 (3 files)

| Fragment ID | 标题 | 文件 | 置信度 |
|---|---|---|---|
| HRV-a1b2c3d4 | 热路径零分配模式 — tuple+deque+缓存 | `kh-hotpath-zero-alloc.md` | 0.9 |
| HRV-e5f6a7b8 | Fail-Closed 网关安全契约 | `kh-failclosed-gateway-contract.md` | 0.9 |
| HRV-c9d0e1f2 | 订单状态机完整性 — terminal guard + partial | `kh-order-statemachine-completeness.md` | 0.9 |

### 3.2 Spec 新增 (3 entries)

| SID | 类别 | 标题 | 目标文件 |
|---|---|---|---|
| S-20260801-a3f1 | coding | 热路径零分配：per-bar/per-signal 管线用 tuple+deque(maxlen)+缓存 | `coding-conventions.md` |
| S-20260801-b7e2 | coding | 订单状态机完整性：timeout 标 terminal+撤单+返回值不弃+terminal guard+partial 建模 | `coding-conventions.md` |
| S-20260801-c5d3 | arch | 禁止跨层 getattr 私有属性 + 同域对象单一权威源 | `architecture-constraints.md` |

### 3.3 Issue 新增

无（所有 bug/risk 已在源工件的 odyssey 流程中处理完毕）。

### 3.4 来源分布

所有 4 个新片段均来自工件 #6（trade-main-path odyssey），因为：
- 工件 #1-2（M4 回顾 + Phase 6 报告）：全部 7 个 M4 patterns 已在 harvest-report-20260730 收割
- 工件 #3（structlog bridge）：已在 coding-conventions + debug-notes 固化
- 工件 #4-5（L6 sibling sinks + strategy engine L6 decouple）：已在 S-20260724-3i37 + S-20260724-02ek + learnings.md 固化
- 工件 #7（security hardening 回顾）：全部 12 条 insight 已在 learnings.md 固化
- 工件 #8（Station UI frontend）：全部 4 条 UI spec 已在 ui-conventions.md 固化

---

## 4. 去重详情

### 已存在于 knowhow (7 items skipped)

| F# | 标题 | 已有位置 |
|---|---|---|
| F1 | Pending 台账三元语义 | `kh-multi-symbol-patterns.md §1` |
| F2 | 多 symbol 六项架构决策 | `kh-multi-symbol-patterns.md §2` |
| F3 | TOCTOU 四象限矩阵 | `kh-multi-symbol-patterns.md §3` |
| F4 | partial_confirm 累积 notional | `kh-multi-symbol-patterns.md §1` |
| F5 | 策略实例跨 symbol 污染 | `kh-multi-symbol-patterns.md §4` |
| F6 | CCXT 实例共享约束 | `kh-multi-symbol-patterns.md §5` |
| F7 | PaperGateway partial_fill_ratio | `kh-multi-symbol-patterns.md §7` |

### 已存在于 specs (12 items skipped)

| 标题 | 已有 SID/位置 |
|---|---|
| L6 MonitoringSink Protocol 注入 | S-20260724-3i37 (coding-conventions) |
| L6 跨层耦合禁用 in-function import 审计规避 | S-20260724-02ek (architecture-constraints) |
| structlog stdlib 桥接 | coding-conventions:35 + debug-notes:20 |
| flush_signals GIL 原子性 | S-20260731-c4n5 (coding-conventions) |
| Timeout 四象限 Fail-Closed | S-20260731-b9m3 (architecture-constraints) |
| fail-silent 不可复用合法结果值 | S-20260724-elsu (coding-conventions) |
| Dark dashboard token 系统 | S-20260722-ui01 (ui-conventions) |
| 异步提交反馈三件套 | S-20260722-ui02 (ui-conventions) |
| WCAG 关键 4 项 | S-20260722-ui03 (ui-conventions) |
| 数值渲染 guard helper | S-20260722-cg01 (ui-conventions) |
| 安全 hardening 7 insights | learnings.md (INS-ed9b4bab 等 7 条) |

### 已存在于 learnings (2 items skipped)

| 标题 | 已有位置 |
|---|---|
| Grep-after-Edit cache lag | INS-ca90827c (learnings.md) |
| 幂等状态下沉致测试顺序依赖 | S-20260724-3jyz (learnings.md) |

---

## 5. 创建/修改文件清单

### 新建 (3 files)
- `.workflow/knowhow/kh-hotpath-zero-alloc.md`
- `.workflow/knowhow/kh-failclosed-gateway-contract.md`
- `.workflow/knowhow/kh-order-statemachine-completeness.md`
- `.workflow/harvest/harvest-report-2026-08-01.md` (本报告)

### 修改 (2 files)
- `.workflow/specs/coding-conventions.md` — 追加 S-20260801-a3f1 + S-20260801-b7e2
- `.workflow/specs/architecture-constraints.md` — 追加 S-20260801-c5d3
- `.workflow/harvest/harvest-log.jsonl` — 追加 4 条 HRV-* 记录

---

## 6. 问题与建议

### 无问题
全部 8 工件成功读取和解析，无格式异常或读取失败。

### 建议
1. **trade-main-path 19 deferred issues**（ISS-001~018）已在前次 odyssey 落入 issues.jsonl，本次未重复创建
2. **M4 retrospective 建议项**（Helper 合并、async teardown、性能阈值 env 化）为低优先级改进，暂不创建 issue
3. 下次 harvest 建议关注 trade-main-path deferred issues 的解决进度

---

*Report generated: 2026-08-01*
