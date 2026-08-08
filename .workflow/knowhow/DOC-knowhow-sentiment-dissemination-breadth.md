---
title: 情绪分析传播广度感知(聚类+prompt 注入,+8 个百分点)
category: ai,sentiment,research
createdBy: manage-harvest
sourceRef: deep-research-20260718 F12
type: knowhow
status: active
related:
  - DOC-knowhow-fingpt-v33-finbert-upgrade
---
现有 LLM 情绪分析方法通常只关注新闻内容本身、忽略信息传播广度(dissemination breadth),削弱短期走势预测准确性。AAAI 2025 Workshop 论文(arXiv:2412.10823)方法:通过聚类公司相关新闻评估触达与影响力,并将传播广度、上下文数据与明确指令注入 prompt,可使股价走势预测准确率提升约 8 个百分点(55%→63%)。QuantFlow 的 strategy/sentiment.py 的 analyze_text 仅对单条文本打分、无传播广度元数据,正属于被批评的范式。来源: arxiv.org/abs/2412.10823。注: N=380 小样本 workshop 论文,做的是周度走势方向预测(非点位预测),8% 是绝对百分点非相对。confidence: high(3-0)。