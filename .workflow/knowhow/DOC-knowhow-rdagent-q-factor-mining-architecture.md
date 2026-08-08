---
title: RD-Agent(Q) 五单元闭环 + Co-STEER DAG + bandit 调度因子挖掘架构
category: ai,factor-mining
createdBy: manage-harvest
sourceRef: deep-research-20260718 F10
type: knowhow
status: active
---
Microsoft RD-Agent(Q)(NeurIPS 2025, arXiv:2505.15155)是 QuantFlow 规划中 Qlib RD-Agent 因子挖掘层的直接参考。架构要点:(1) 五单元闭环 Specification→Synthesis→Implementation→Validation→Analysis;(2) Co-STEER 代码生成 agent 用 DAG G=(V,E) 表示任务依赖+拓扑排序,维护 task-code-feedback 三元组知识库做检索式复用;(3) 因子-模型联合优化用 contextual two-armed bandit(linear Thompson sampling),8 维状态向量(IC/ICIR/RankIC/RankICIR/ARR/IR/-MDD/SR),决策下一步优化 factor 还是 model,消融 Bandit(ARR0.1421)>Random>LLM-based。CLI 骨架 commit b439ce7 已存在(rdagent fin_factor/fin_model/fin_quant)。注: 2x ARR 基准为 medium(2-1),实验在股票市场跨资产泛化未直接验证,仅作架构范式。