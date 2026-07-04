# 多参数 ZigZag 交叉验证取 >80% 重叠共识转折点

**Source**: brainstorm-elliott-wave-20260601 (Q1 + C-002)
**Tags**: elliott-wave, zigzag, accuracy

问题：ZigZag 参数敏感性导致不同参数标记不同转折点，浪型识别不稳定。

方案：多参数 ZigZag 交叉验证（如 thresholds=[3.0, 5.0, 7.0]），取 >80% 重叠的共识转折点。min_overlap 参数可配置，适应不同品种特征。

Fallback：无共识时使用单 ZigZag + 降低置信度标记。
