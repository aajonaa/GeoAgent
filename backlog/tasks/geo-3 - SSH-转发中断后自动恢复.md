---
id: GEO-3
title: SSH 转发中断后自动恢复
status: To Do
assignee: []
created_date: '2026-10-10 06:14'
labels:
  - proposed
  - reliability
milestone: m-1
dependencies: []
priority: high
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
15015 曾因本机 SSH 隧道退出而不可用，A100 本身正常。现有 keepalive 不会重启退出的进程。仅记录建议，本轮不实施。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 受控断线后恢复访问且不产生重复监听
- [ ] #2 提供连接状态与停止方法
- [ ] #3 不改凭证或影响 A100 应用
<!-- AC:END -->
