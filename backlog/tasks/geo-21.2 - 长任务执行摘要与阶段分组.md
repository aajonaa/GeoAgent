---
id: GEO-21.2
title: 长任务执行摘要与阶段分组
status: In Progress
assignee:
  - '@QoderCN'
created_date: '2026-11-26 14:52'
updated_date: '2026-11-26 15:58'
labels:
  - frontend ux
dependencies: []
parent_task_id: GEO-21
priority: high
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
真实任务会产生数百事件和数十工具调用，原始时间线难以快速理解。增加任务摘要、阶段分组、异常聚合和渐进披露，同时保留完整回执。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 顶部展示当前阶段、关键里程碑与未完成事项
- [ ] #2 工具调用可按阶段或来源域分组，重复调用不平铺挤占主视图
- [ ] #3 失败与部分完成可辨识，完整工具回执仍可访问
- [ ] #4 桌面与手机浏览器验证通过并保存回执
<!-- AC:END -->
