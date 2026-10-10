---
id: GEO-2
title: 试用 GeoAgent 项目看板并收集反馈
status: In Progress
assignee: []
created_date: '2026-10-10 06:14'
updated_date: '2026-10-10 06:27'
labels:
  - management
  - trial
milestone: m-0
dependencies: []
priority: medium
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
过去工作分散在长对话中，难以确认状态和版本变化。先试用本机看板，保持进行中，等待用户决定是否正式采用。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 能够查看中文任务卡、验收条件和版本文档
- [ ] #2 用户确认看板流程适合继续使用
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
本轮扩展：保留本机看板；新增 Linux 启动与独立 systemd 服务；只提交管理文件；将同一提交的管理快照同步到 A100；经 SSH 16420 访问，不动 Agent 15015。
<!-- SECTION:NOTES:END -->
