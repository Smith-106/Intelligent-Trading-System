# v0.11.0 测试报告

## 后端（Python 3.14 / pytest）
- 分区单测：1830 + 686 + 870 = 3386 passed，`-m "not slow"`
- 唯一失败：已知日期敏感预存用例（test_load_sealed_panel_happy_path，
  固定 base fixture 问题，与本版变更无关）
- 新增测试面：
  - test_cache_coalesce.py：single-flight 单次计算 + 读不阻塞
  - test_fakedatastore_contract.py：DataStoreProtocol 收集期契约
  - sink env fallback ×3（告警装配回归守护）
  - 限流路由不变量、Origin 策略矩阵（SEC-REV020）

## 前端（vitest@4 + Testing Library）
- `npm test`：7/7 passed（CopyableText ×3 / useMutationFeedback ×2 /
  usePanelQuery ×2）——前端测试基建自本版从零建立

## 门禁状态
- tsc -b / oxlint（54 文件 101 规则）/ vite build 全绿
- ruff check/format 全绿；mypy strict 存量违规为历史遗留（见 v0.9.0 已知问题 #2）

## 覆盖率
- fail_under=100 棘轮维持；覆盖率数字以 CI 最新运行为准（本地分区跑不含 slow）
