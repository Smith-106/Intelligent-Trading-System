# v0.11.0 — Station 可视化与信任升级

发布日期：2026-08-23 · 前一版本：[v0.10.0](../v0.10.0.md)

## 主题

本轮让 Station 从「能看状态」进化到「能看行情、信得过数字」：新增多周期
并行分析与 K 线图表面板；集中修复一批导致误判风险的正确性缺陷（回撤分级、
NO-GO 徽章、实盘双因子确认）；完成两轮安全加固与一轮性能实测优化；告警与
配置从此开箱即用。

## 主要变更

### 行情可视化：24 周期并行分析 + 图表面板
- 只维护 {5m, 1d} 基础网格，本地派生全部 24 档周期（含交易所不原生支持的 45m/7h/16h/32h）
- lightweight-charts 蜡烛图 + 成交量副图，深浅主题自动重配色，symbol/周期/成交量选择持久化
- 新端点 `POST /api/analysis/multi-tf`：单次基础读取 → 内存重采样，部分成功语义

### 数字可信：风险信号正确性专项
- **回撤符号契约修复（Critical）**——回撤危险分级此前永远不触发，现已生效
- 净值指标对照初始资金分级（原「equity > 0 即绿」）；NO-GO 结果不再渲染成绿色徽章
- 实盘启动需「勾选确认 + 口令」双因子（原任一即可）
- 持仓/订单字段漂移导致的 NaN% 渲染修复

### 更快的管理台（实测）
- overview 冷启动雪崩消除：并发请求合并为一次扫描（~1.6–2.3s × N → 一次）
- strategies 面板 ~340ms → ~2ms；缓存重算不再阻塞普通读写

### 安全加固两轮（共识审计 REV-010 + SEC-REV020）
- **X-Forwarded-For 伪造限频绕过修复（本轮最高危）**：仅信任白名单代理
- 同源策略收紧、CSP 强化、审计签名密钥外置（`QUANTFLOW_AUDIT_HMAC_KEY`）、日志全面脱敏
- 未知策略 id 错误码 500→400 归一

### 告警与配置开箱即用
- Telegram 告警环境变量装配修复（此前配置了也收不到通知——如实说明）
- `.env.example` 全面重写：删 6 个幽灵变量、补 compose 必填变量与 Station 安全变量

### CLI ↔ Web 行为一致
- research/optimize/validate 能读到 download 的默认产出（resolve_symbol 全链路）
- validate 时间窗参数生效；`status` 反映真实策略目录

### 可访问性与操作手感
- 键盘可达的策略卡、屏幕阅读器播报（role=alert/status）、可复制的 ID/订单号/路径
- `useMutationFeedback` 统一操作反馈：即时 toast + 可追溯内联提示

### 工程质量
- 前端测试从 0 到 1（vitest@4 + Testing Library，`npm test`）
- 共享 FakeDataStore + Protocol 收集期契约测试；CLI/数据层结构拆分（行为不变）

## 兼容性与升级

详见 [upgrade-guide.md](upgrade-guide.md)。要点：

1. docker compose 现强制要求 `GRAFANA_ADMIN_PASSWORD` / `QUANTFLOW_REDIS_PASSWORD`（缺失即拒启）
2. 无 Origin 头的非回环变更请求返回 403
3. optimize/validate 失败退出码 0 → 1（自动化脚本如依赖旧行为请适配）

## 已知问题

见 [known-issues.md](known-issues.md)。
