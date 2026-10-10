---
id: GEO-4
title: 统一发布记录与线上版本标识
status: To Do
assignee: []
created_date: '2026-10-10 06:14'
labels:
  - proposed
  - release
milestone: m-1
dependencies:
  - GEO-1
priority: high
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
源码提交与 A100 叠加部署不能直接对应，需要可辨认的构建身份，避免把已推送误认为已上线。仅记录建议。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 设置页显示实际构建而非仅显示工作目录
- [ ] #2 每次发布关联任务、完整 SHA、验收证据及回滚目标
- [ ] #3 未验证或未部署明确显示未完成
<!-- AC:END -->
