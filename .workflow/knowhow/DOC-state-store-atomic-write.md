---
title: 状态存储 StateStore 原子写入模式：tmp + os.replace 安全写入
category: reliability
createdBy: "harvest:wave1-precheck"
sourceRef: maestro-wave1-precheck-20260803-20260803-075540
---
# 状态存储原子写入模式

## 适用场景
需要持久化运行时状态（检查点/配置/缓存），保证写入中途崩溃不损坏已存在数据。

## 设计要点

1. **tmp + os.replace 原子写入**：先写入临时文件，成功后再 `os.replace` 替换目标文件
2. **schema_version 版本保护**：文件头包含版本号，读取时校验格式兼容性
3. **fail-closed 读取**：corrupt 文件返回 None + critical 日志，不尝试恢复损坏数据
4. **调用方责任**：返回 None 时调用方自行决定降级策略

## 实现参考
```
state_store.py:
  - save(): tmp 文件写入 → os.replace 原子替换
  - load(): 读取 → schema_version 校验 → 返回数据/None
  - corrupt 检测: JSON parse 失败 / 字段缺失 / 版本不匹配
```

## 来源
maestro-wave1-precheck session (2026-08-03), correctness spotcheck: state_store.py