---
id: GEO-21.2
title: 长任务执行摘要与阶段分组
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-26 14:52'
updated_date: '2026-11-27'
labels:
  - frontend ux
  - release-0.23
dependencies: []
references:
  - 'deployed-build:7ef321a0dc127cf6aea67034e73456cd5e53f9658aa2a9697db1d38995fb9cb2'
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ux-task-summary-20261127/verification.json
  - 'git-commit:89f176c0c4cf3041adf9ef9601a2e9e04415bd8c'
modified_files:
  - geological_agent/team/web/images.js
  - geological_agent/team/web/index.html
  - geological_agent/team/web/style.css
  - geological_agent/team/web/timeline.css
  - geological_agent/team/web/timeline.js
  - tests_local/experience-regression.js
  - tests_local/live-ui-regression.js
  - tests_local/test_hitl.py
  - tests_local/timeline-regression.js
  - tests_browser/task_summary_e2e.py
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
- [x] #1 顶部展示当前阶段、关键里程碑与未完成事项
- [x] #2 工具调用可按阶段或来源域分组，重复调用不平铺挤占主视图
- [x] #3 失败与部分完成可辨识，完整工具回执仍可访问
- [x] #4 桌面与手机浏览器验证通过并保存回执
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. 从真实 stage_timing、status 与终止事件提取当前阶段，仅展示已观察里程碑和未完成事项。
2. 按来源域与精确工具名称分组调用，保留每次调用、完整回执和下载入口。
3. 聚合失败、执行中、可重试错误、检索不可用、响应中断与部分终态，完成后清理历史未完成提示。
4. 增加前端回归与桌面/手机 Playwright 回放，覆盖运行、needs_input、completed 和懒加载稳定性。
5. 按零活跃任务门禁部署，核对安装与公网资产、安装后测试和公网浏览器回放后提交并推送。
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
已实现真实当前阶段、已观察里程碑、未完成事项聚合，以及来源域/工具名称两级分组；不推测研究计划、完成百分比或隐藏进度。完整工具回执与认证下载入口保留，终止后缺失回执显示为未完成而非执行中。JavaScript 语法与三组前端回归通过；A100 候选和安装后定向测试均为 6 passed/7 deselected；1440 与 390 候选及公网 Playwright 覆盖运行、部分终态、完成清理、完整回执下载、无横向溢出和无页面错误。

已发布 0.23 / 7ef321a0dc12，安装哈希、公网版本化资产、安装后测试与两档公网回放通过。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/ux-task-summary-f1e46aa8c1。首次发布因公网注册配置注入导致原始 HTML 哈希比较失败，安装后测试通过并自动回滚 0.22；失败回执保留于 attempt-1-failed-public-hash，校验改为还原运行时配置后逐字比较模板，重试通过。定向测试范围之外的完整 test_hitl.py 未声明全绿，详见 verification.json。

Git 完成：功能与测试提交 89f176c0c4cf3041adf9ef9601a2e9e04415bd8c 已推送 origin/codex/orebogao-geo-ux-global-state，git ls-remote 核对远端尖端一致。本条完成回执通过独立 Backlog 文档提交推送。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GEO-21.2 已完成并上线 0.23：长任务展示真实阶段、已观察里程碑与未完成事项，工具调用按来源域和名称折叠且完整回执可访问；桌面/手机候选与公网回放通过，功能提交 89f176c 已推送，旧构建回滚备份保留。
<!-- SECTION:FINAL_SUMMARY:END -->
