# Qoder IDE 设置清单（基于官方文档核对，2026-07）

## 第一节：mcp.json 使用说明

- **目标位置**：`C:\Users\niko\.qoder\mcp.json`（当前为空 `{ "mcpServers": {} }`），优先通过 IDE 的 MCP 设置面板编辑，而非直接改磁盘文件。
- **schema 已验证项**：
  - 顶层为 `mcpServers` 键，按 server 名为 key；
  - STDIO 服务使用 `command` / `args` / `env`（无需 `type` 字段）；
  - SSE 服务使用 `"type": "sse"` + `url`；
  - 来源：https://docs.qoder.com/zh/user-guide/chat/model-context-protocol
- **需核对项**：
  1. fetch 的 SSE URL 为推测值，需从 MCP 市场复制真实端点；
  2. filesystem 服务未在 Qoder 文档展示，添加后需在 IDE 确认链接图标变绿；
  3. SSE `headers` 字段是否支持未验证；
  4. Request Timeout 不在 JSON 中，保存服务后在"服务详情 → 服务超时时长"下拉框设置。
- **安全提醒**：GitHub PAT 切勿提交到 Git。

## 第二节：IDE 设置清单

通用入口：`Ctrl+Shift+,` → Qoder 设置。

| # | 设置项 | 操作路径 | 说明 | 验证状态 |
|---|--------|----------|------|----------|
| 1 | 代码库索引忽略 | 设置 → 代码库索引 → 忽略文件 → 管理 | 添加 `node_modules/`、`dist/`、`build/`、`.git/`、`.venv/`、`.ruff_cache/`、`.mypy_cache/`、`.pytest_cache/`、`.workflow/`、`data/parquet/`；也可在项目根建 `.qoderignore`（.gitignore 中的默认已排除） | 已验证 |
| 2 | 项目级 Rules | 设置 → 规则 → 添加 | 四种类型：始终生效 / 指定文件生效 / 模型决策 / 手动 @rule；总量上限 10 万字符；存放于 `.qoder/rules`；Qoder 自动识别根目录 AGENTS.md | 已验证 |
| 3 | NEXT + 代码补全 | 设置 → 行间建议 → 开启 NEXT | Windows：`Alt+P` 手动触发、`Tab` 接受、`Esc` 拒绝、按住 `Alt` 预览 | 已验证 |
| 4 | 网络代理 | 设置 → 高级 → 网络代理 | 手动 → HTTP 类型 → `http://127.0.0.1:8756`；连通性验证：终端 `curl https://api1.qoder.sh/algo/api/v1/ping` 返回 `pong` | 已验证 |
| 5 | 智能会话工具确认 | 智能会话面板 → Agent 模式 | MCP 工具调用前请求确认（`Ctrl+Enter` 执行）；信任建立后勾选自动运行 | 已验证 |
| 6 | 安全扫描等级 | 设置 → 安全 → 扫描层级 | L1 免费自动；L2 约 5 Credits/500 行，任务收尾执行；L3 约 20 Credits/500 行，推送前执行（Quest 提交下拉 → 扫描并推送）；日常 L1+L2，提交前 L3 | 已验证 |
| 7 | 记忆系统 | 设置 → 记忆，或知识中心 → Memory 面板 | Memory Dream 每天凌晨自动归纳/合并/清理；定期审查即可 | 已验证 |
| 8 | 隐私/遥测 | 见 FAQ 数据安全章节 | 官方声明不存储/不分享代码；仅点赞点踩时匿名化聊天记录；关闭数据上报开关路径文档未给出，需在通用设置中自查 | 政策已验证 / 开关路径未验证 |
| 9 | 自动更新 | 设置（或插件设置）→ 更新设置 | 建议开启；建议使用用户版安装（`%LOCALAPPDATA%`，免管理员）规避 Program Files 提权问题（该影响为推断） | 部分验证 |
| 10 | Quest 模式 | Editor 右上角"打开 Quest" | 个人开发选 Agent 模式（危险命令暂停确认）；Windows 沙箱自研引擎、Win7+ 原生、无需 WSL；workspace 可写、其余只读、`~/.ssh` 不可见 | 已验证 |

## 第三节：来源汇总

- https://docs.qoder.com/zh/user-guide/chat/model-context-protocol （MCP）
- https://docs.qoder.com/zh/user-guide/indexing （索引忽略）
- https://docs.qoder.com/zh/user-guide/rules （Rules）
- https://docs.qoder.com/zh/user-guide/next-edit-suggestion 与 https://docs.qoder.com/zh/plugins/completion （NEXT/补全）
- https://docs.qoder.com/zh/user-guide/configure-network-proxy （代理）
- https://docs.qoder.com/zh/qoder-security-guide （安全扫描）
- https://docs.qoder.com/zh/user-guide/knowledge-engine/memory （记忆）
- https://docs.qoder.com/zh/troubleshooting/common-issue （隐私 FAQ）
- https://docs.qoder.com/zh/plugins/settings 与 https://docs.qoder.com/zh/qoderwork/install-windows （更新/安装）
- https://docs.qoder.com/zh/user-guide/quest/overview 与 https://docs.qoder.com/zh/user-guide/quest/terminal-and-sandbox （Quest/沙箱）
