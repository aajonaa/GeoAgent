---
id: GEO-21.4
title: 终态恢复与下一步动作
status: To Do
assignee: []
created_date: '2026-11-26 14:52'
labels:
  - frontend ux
dependencies: []
parent_task_id: GEO-21
priority: high
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
普通完成、停止和失败终态主要只有复制答复，用户难以从已有上下文继续。提供状态匹配的恢复和继续动作，不自动覆盖旧成果。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 完成态可继续追问或基于本轮成果生成新内容
- [ ] #2 停止态可从停止位置继续，失败态保留上下文重试
- [ ] #3 部分完成展示未完成项，不伪装为全部成功
- [ ] #4 恢复动作经过权限校验且保留原运行与成果版本
<!-- AC:END -->
