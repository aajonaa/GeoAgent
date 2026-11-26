---
id: GEO-21.1
title: 全局任务状态与草稿持久化
status: In Progress
assignee:
  - '@QoderCN'
created_date: '2026-11-26 14:52'
updated_date: '2026-11-26 15:55'
labels:
  - frontend ux
  - release-0.22
dependencies: []
references:
  - 'deployed-build:77af4e8905bf'
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ux-global-state-draftfix-20261126/verification.json
modified_files:
  - geological_agent/team/store.py
  - geological_agent/team/server.py
  - geological_agent/team/web/drafts.js
  - geological_agent/team/web/app.js
  - geological_agent/team/web/hitl.js
  - geological_agent/team/web/index.html
  - geological_agent/team/web/style.css
  - tests_local/test_hitl.py
  - tests_browser/workspace_state_e2e.py
parent_task_id: GEO-21
priority: high
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
切换会话会清空当前运行视图，普通与 HITL 草稿只保存在内存，用户容易误以为任务或输入丢失。提供跨会话任务状态和可恢复草稿。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 切换会话后仍可看到账号正在执行的任务并一键返回
- [x] #2 普通输入与 HITL 文本在刷新后恢复，未上传附件仍在本地保留
- [x] #3 草稿按账号和会话隔离，退出登录后不串号
- [x] #4 桌面与手机浏览器验证通过并保存回执
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. 增加账号级只读活动任务接口，返回运行中任务和待回复请求。
2. 增加全局任务条和轮询，在切换会话时保留跨会话任务入口。
3. 增加按账号/会话隔离的文本草稿与 IndexedDB 附件草稿，覆盖普通输入和 HITL。
4. 增加 API 安全测试及桌面/手机浏览器回放，验证刷新、切换账号、附件恢复和无横向溢出。
5. 按既有发布链路部署，核对公网构建和浏览器行为后提交并推送。
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
已编码并验证：账号级活动任务/待回复接口、全局任务条、按账号与对话或请求隔离的文本草稿、IndexedDB 未上传附件草稿。A100 候选与安装后定向测试均为 6 passed/7 deselected；1440 与 390 Playwright 覆盖跨会话返回、刷新恢复、HITL 文本/选项/附件、账号隔离、新对话首次提交清理、无横向溢出和无页面错误。已发布 0.21（1ae0f73f7c5e）及修复首次新对话草稿重复的 0.22（77af4e8905bf），公网资产哈希、安装后测试与两档公网回放通过。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/ux-global-state-draftfix-6a6cc9688b。定向测试范围之外的完整 test_hitl.py 未声明全绿，详见 verification.json。Git 提交与推送待执行。
<!-- SECTION:NOTES:END -->
