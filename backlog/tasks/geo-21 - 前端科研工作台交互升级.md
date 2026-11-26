---
id: GEO-21
title: 前端科研工作台交互升级
status: In Progress
assignee: []
created_date: '2026-11-26 14:52'
updated_date: '2026-11-26 15:55'
labels:
  - frontend ux
dependencies: []
priority: high
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
现有前端具备执行回放、HITL 和成果快照，但跨会话任务感知、长执行信息架构、科研证据追溯和终态恢复仍不完整。按五个独立交付点逐项实现、测试、部署和推送，保留现有安全边界与真实证据语义。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 五项交互分别有独立验收、部署与 Git 推送回执
- [ ] #2 每项上线后无新增回归，旧构建可回滚
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
GEO-21.1 已完成编码、定向验证和 0.22 部署，正在完成本项 Git 提交与推送；GEO-21.1 推送回执补齐后开始 GEO-21.2。
<!-- SECTION:NOTES:END -->
