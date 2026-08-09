# 如何把本目录发成 **public** 仓库（方案 B）

> 主仓 `Intelligent-Trading-System` **保持 private**。  
> 本目录是可公开子集：定位、合成 gate 样例、无密钥说明。  
> **不要**把 `data/`、`.env`、真实全窗 PnL JSON、API 密钥拷进 public 仓。

## 推荐：独立 public 仓

```bash
# 1) 在 GitHub 新建空 public 仓，例如 quantflow-docs-demo
# 2) 本地导出本目录
cd /path/to/智能交易系统
rm -rf /tmp/quantflow-docs-demo
mkdir -p /tmp/quantflow-docs-demo
cp -r docs/public-demo/* /tmp/quantflow-docs-demo/
cd /tmp/quantflow-docs-demo
git init
git add .
git commit -m "docs: QuantFlow public demo pack (Apache-2.0)"
# 3) 关联并推送（替换 OWNER/REPO）
git branch -M main
git remote add origin https://github.com/OWNER/quantflow-docs-demo.git
git push -u origin main
# 4) GitHub → Settings → 确认 Public；About 填：paper-first research OS docs
```

## 公开范围（白名单）

| 包含 | 不包含 |
|------|--------|
| POSITIONING.md | quantflow/ 源码 |
| sample_gate.json（合成） | data/parquet、真实 gate 结果 |
| sample_fee_slip_grid.json | OKX 密钥 / .env |
| README / LICENSE Apache-2.0 | 全窗 cost JSON 原始研究产物（可选：只放摘要 MD） |

## 成功标准（方案 B）

- 第三人无需 API key 能读懂：定位、非目标、Path A/B、GO 需要成本网格。  
- **不**用 stars 或名义 Sharpe 作 KPI。  
- 私有主仓 visibility **不变**。

## 升级到 C 的触发条件（备忘）

- paper 日课稳定 ≥ 数周  
- ≥3 Baseline 合同可复现  
- 维护 issue/PR 的意愿明确  
- 全仓 secret 扫描通过后再考虑 core 开源
