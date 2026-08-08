---
title: FinBERT→FinGPT v3.3 升级路径(单卡 RTX 3090/7.25)
category: ai,sentiment,upgrade-path
createdBy: manage-harvest
sourceRef: deep-research-20260718 F11
type: knowhow
status: active
related:
  - DOC-knowhow-sentiment-dissemination-breadth
---
QuantFlow 当前 FinBERT 情绪模块可升级为 FinGPT v3.3(Llama2-13B 基座):在 FPB/FiQA-SA/TFNS/NWGI 合成基准加权 F1 达 0.882,自称优于 GPT-4 与 ChatGPT 微调,单卡 RTX 3090、17.25 小时、7.25 成本即可微调(QLoRA int4 版本 .15/次)。对比 BloombergGPT 的 512×A100/53天/~M,让金融 LLM 对个人/小团队可行。来源: ai4finance-foundation/fingpt。注: beat GPT-4 为来源自报,2023 年基准对 2026 SOTA 非最新,作为 FinBERT 的直接可比升级路径成立而非当前最优。confidence: medium-high(2-1)。