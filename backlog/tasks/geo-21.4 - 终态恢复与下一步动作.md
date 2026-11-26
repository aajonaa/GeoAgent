---
id: GEO-21.4
title: 终态恢复与下一步动作
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-26 14:52'
updated_date: '2026-11-27 04:24'
labels:
  - frontend ux
  - release-0.25
dependencies: []
references:
  - >-
    deployed-build:ea6bb60b8d3fa21e7f55399ad7a4b9cfa33dc6713c192b3391aaf9088c5c4816
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ux-terminal-recovery-20261127/deployment.json
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ux-terminal-recovery-20261127/public-browser/result.json
  - 'git-commit:7e7ce52b0b3ff6caf0b6ee1b82bde2201379417d'
modified_files:
  - geological_agent/team/server.py
  - geological_agent/team/conversation_memory.py
  - geological_agent/team/web/app.js
  - geological_agent/team/web/images.js
  - geological_agent/team/web/recovery.js
  - geological_agent/team/web/index.html
  - geological_agent/team/web/style.css
  - tests_local/test_terminal_recovery_api.py
  - tests_local/terminal-recovery-regression.js
  - tests_local/test_hitl.py
  - tests_browser/terminal_recovery_e2e.py
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
- [x] #1 完成态可继续追问或基于本轮成果生成新内容
- [x] #2 停止态可从停止位置继续，失败态保留上下文重试
- [x] #3 部分完成展示未完成项，不伪装为全部成功
- [x] #4 恢复动作经过权限校验且保留原运行与成果版本
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. 按完成、停止、失败和部分完成状态提供恢复动作，保留现有运行详情与文件版本。
2. 增加账号、CSRF、来源归属、对话、状态和动作校验，只准备可编辑草稿。
3. 恢复提交继续经过研究计划确认门禁，在同一对话新建运行并记录来源运行。
4. 将原问题、终态、原因、活动、成果代次及有界执行事件显式注入模型上下文。
5. 完成 API、前端回归、桌面/手机浏览器、安装后与公网验收，按独立交付提交推送。
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
coded：完成态支持继续追问和基于成果生成；停止/取消/中断/预算耗尽/部分完成支持续写，失败态支持保留上下文重试。恢复不覆盖旧运行或成果，提交仍须确认研究计划。
verified：A100 候选和安装后分别通过 29 项恢复 API、47 项计划 API 和 6 项相关 HITL 测试；本地 9 条检查命令与 4 组回归通过。1440/390 候选和公网 Playwright 覆盖动作载荷、计划门禁、失败重试、部分完成变体、原运行保留、无溢出和无页面错误。
released：0.25 版本记录已创建；Git tag/Release 未创建。
deployed：0.25 / ea6bb60b8d3f，完整源码 ea6bb60b8d3fa21e7f55399ad7a4b9cfa33dc6713c192b3391aaf9088c5c4816，安装哈希、安装后测试、公网资产与两档回放通过。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/ux-terminal-recovery-8e553997c4。
失败证据保留：r2 候选曾因助手作用域错误失败；首次公网回放曾因任意请求数阈值失败并自动回滚。两者均已归档，阈值改为关键资产集合校验后重新通过全部发布门禁。
Git 完成：功能与测试提交 7e7ce52b0b3ff6caf0b6ee1b82bde2201379417d 已推送 origin/codex/orebogao-geo-ux-global-state，git ls-remote 核对远端尖端一致。本条完成回执通过独立 Backlog 文档提交推送。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GEO-21.4 已完成并上线 0.25：终态提供状态匹配的恢复与下一步动作，恢复经过权限和来源校验、保留原运行与成果版本，并在确认研究计划后携带原执行上下文新建运行；候选/安装后测试及桌面/手机公网回放通过，功能提交 7e7ce52 已推送，回滚备份保留。
<!-- SECTION:FINAL_SUMMARY:END -->
