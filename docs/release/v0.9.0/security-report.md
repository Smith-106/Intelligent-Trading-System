# v0.9.0 安全报告

- **无新增第三方依赖**（CCXT 已有；Binance 归档走标准库 HTTP）
- **API 凭证**：全部命令仅公开端点，无需 API key；凭证仍只从 ENV 读取
- **供应链**：修复 workflow 中两个不存在的 action SHA（setup-python/upload-artifact）为官方真实 SHA，保持 SHA-pin 策略
- **路径安全**：resolve_symbol 全部候选经 validate_symbol 守卫（SYMBOL_PATTERN）；归档脚本显式映射表禁启发式路径推导
- **数据完整性**：发布产物 SHA256SUMS.txt 入册；迁移 manifest 含回滚清单
