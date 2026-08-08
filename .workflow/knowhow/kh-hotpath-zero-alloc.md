---
title: "Hotpath zero-allocation patterns"
type: knowhow
tags: [performance, hotpath]
status: active
---
---
id: kh-hotpath-zero-alloc
title: 热路径零分配模式 — per-bar/per-signal 管线优化
tags:
  - performance
  - hot-path
  - deque
  - tuple
  - cache
  - risk-engine
  - allocation
source: "harvest:20260723-improve-odyssey-trade-main-path"
created: 2026-08-01
related:
  - "spec:project:coding-conventions-016"
---


# 热路径零分配模式

## 问题

风控/信号管线中 `risk_engine.check()` 等每 bar/信号执行的函数，若每次调用都分配新 list、做切片、重算纯函数，在高频场景下产生大量短生命周期对象，增加 GC 压力和延迟。

## 模式

### 1. bound-method tuple 在 `__init__` 一次性构建

```python
# BAD: 每次 check() 都创建新 list
def check(self):
    checks = [self._check_daily_loss, self._check_position_limit, ...]
    for c in checks:
        ...

# GOOD: __init__ 构建 tuple（不可变，零 per-call 分配）
def __init__(self):
    self._checks = (
        self._check_daily_loss,
        self._check_position_limit,
        ...
    )

def check(self):
    for c in self._checks:  # tuple 迭代，零分配
        ...
```

### 2. deque(maxlen=N) 替代 list + [-N:] 切片

```python
# BAD: O(n) 复制每次切片
self._history = []
self._history.append(value)
recent = self._history[-500:]  # O(n) 复制

# GOOD: O(1) 自动驱逐
from collections import deque
self._history = deque(maxlen=500)
self._history.append(value)  # O(1)，自动驱逐旧值
```

### 3. 纯函数按失效键缓存

```python
# BAD: 每次 check 都重算 np.percentile
def _check_var(self):
    return np.percentile(self._history, 5)

# GOOD: 按 history len 缓存（len 变化才需重算）
def __init__(self):
    self._var_cache = None
    self._var_cache_len = 0

def _check_var(self):
    if len(self._history) != self._var_cache_len:
        self._var_cache = np.percentile(self._history, 5)
        self._var_cache_len = len(self._history)
    return self._var_cache
```

## 测量方法

1. 定位每 bar/信号调用的函数（如 `risk_engine.check`）
2. 检查其内是否每次 `new` list / 切片 / 重算纯函数
3. 改为 `__init__` 构建 tuple + deque(maxlen) + 缓存

## 应用范围

- `risk_engine.check` 管线（已应用：tuple + deque + VaR 缓存）
- 任何 per-signal/per-bar 计算管线
- 信号生成器的后处理链

## 实测效果（trade-main-path odyssey）

- risk_engine.check(): 每信号 O(n) list 分配 + slice → O(1) tuple 迭代
- VaR 重算: 每信号 np.percentile → 缓存命中复用
- 1500 tests passed, 0 regression
