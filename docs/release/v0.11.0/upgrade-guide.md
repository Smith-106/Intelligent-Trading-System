# v0.11.0 升级指南（0.10.0 → 0.11.0）

## 破坏性变更（行为面）
1. **docker compose 必填变量**：`GRAFANA_ADMIN_PASSWORD` / `QUANTFLOW_REDIS_PASSWORD`
   缺失或为空时 compose fail-fast 拒启——在 `.env` 中填入后再 `docker compose up -d`。
2. **同源策略收紧**：未配置 Station token 时，非回环来源且缺失 Origin 头的
   变更请求返回 403。反向代理场景请配置 `STATION_TRUSTED_PROXIES`。
3. **退出码语义**：`quantflow optimize` / `quantflow validate` 失败时退出码
   由 0 改为 1。依赖旧「永远 0」行为的自动化脚本需适配。
4. **对账审计签名**：硬编码测试密钥已移除。生产环境请设置
   `QUANTFLOW_AUDIT_HMAC_KEY`，否则审计链保持未签名状态（有明确警告日志）。

## 升级步骤
1. `git pull && pip install -e ".[dev]"`
2. 对照新版 `.env.example` diff 你的 `.env`：6 个幽灵变量已删除
   （REDIS_HOST/PORT/DB/PASSWORD、OKX_SANDBOX、DUCKDB_PATH、PARQUET_PATH），
   新增 compose 必填与 Station 安全变量
3. 前端如从源码构建：`cd frontend && npm ci && npm run build`
4. 验证：`python -c "import quantflow; print(quantflow.__version__)"` → `0.11.0`

## 注意事项
- 无数据迁移；parquet/DuckDB 分区结构不变
- 告警 Telegram 变量在本版才真正生效——此前配置过但没收到通知属正常，
  本版起 sink 回落读取环境变量装配
