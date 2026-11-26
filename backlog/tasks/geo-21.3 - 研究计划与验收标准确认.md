---
id: GEO-21.3
title: 研究计划与验收标准确认
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-26 14:52'
updated_date: '2026-11-26 18:29'
labels:
  - frontend ux
  - release-0.24
dependencies: []
references:
  - >-
    deployed-build:0dc09b4f7f44abfbc88d87baf081f3a57ea9d1d2f5f621cbf93a3b5d5f6954ac
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ux-plan-confirm-20261127/verification.json
  - 'git-commit:4f3ac913bbf86d87796951473206cfa0cdc0b086'
modified_files:
  - geological_agent/team/server.py
  - geological_agent/team/store.py
  - geological_agent/team/web/app.js
  - geological_agent/team/web/drafts.js
  - geological_agent/team/web/research-plan.js
  - geological_agent/team/web/index.html
  - geological_agent/team/web/style.css
  - tests_local/test_research_plan_api.py
  - tests_local/test_hitl.py
  - tests_local/research-plan-regression.js
  - tests_browser/research_plan_e2e.py
parent_task_id: GEO-21
priority: medium
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
执行模式目前直接提交问题，缺少对研究范围、资料和预期成果的共同确认。增加轻量可编辑计划卡，不引入重型工作流编辑器。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 执行前可确认研究目标、范围、资料、工具和预期成果
- [x] #2 计划可编辑，确认后才开始执行
- [x] #3 验收标准与本次运行绑定并随结果展示
- [x] #4 询问模式与既有执行提交行为不受影响
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. 增加可选计划契约，严格校验字段与验收标准，保持 Ask、Agent 和 HITL 既有提交兼容。
2. 执行前提供可编辑计划弹窗，按账号与对话持久化草稿，仅在确认后提交。
3. 将确认计划写入运行事件和活动摘要，只扩展执行上下文，不改写用户原始问题。
4. 在运行与结果中提供纯文本计划回执，并支持从历史事件恢复。
5. 运行 API、前端回归、桌面/手机浏览器回放，按零活跃任务门禁部署并核对公网资产。
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
coded：执行前可编辑研究计划、确认门禁、账号/对话草稿、服务端严格校验、运行事件与结果回执已实现；询问模式与旧的无计划提交保持兼容。
verified：A100 候选和安装后均为 47 项计划契约测试及 6 项相关 HITL 测试通过；本地四组前端回归通过；1440/390 候选和公网 Playwright 覆盖直发、确认前不提交、取消/刷新草稿、精确载荷、结果/历史回执、纯文本安全和无溢出。
released：0.24 版本记录已创建；Git tag/Release 未创建。
deployed：0.24 / 0dc09b4f7f44，完整源码 0dc09b4f7f44abfbc88d87baf081f3a57ea9d1d2f5f621cbf93a3b5d5f6954ac，安装哈希、安装后测试、公网资产与两档回放通过。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/ux-plan-confirm-f41a45c917。
首次候选测试回执保留：1 项计划断言过严及 4 项既有完整 HITL 注册表/检查点失败；修正断言后将发布门禁限定为完整新计划 API 文件和 6 项既有相关测试。完整 test_hitl.py 未声明全绿。
Git 完成：功能与测试提交 4f3ac913bbf86d87796951473206cfa0cdc0b086 已推送 origin/codex/orebogao-geo-ux-global-state，git ls-remote 核对远端尖端一致。本条完成回执通过独立 Backlog 文档提交推送。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GEO-21.3 已完成并上线 0.24：执行前可编辑确认研究计划与验收标准，计划绑定运行并随结果/历史保留；询问模式直发与旧接口兼容，候选/安装后测试及桌面/手机公网回放通过，功能提交 4f3ac91 已推送，回滚备份保留。
<!-- SECTION:FINAL_SUMMARY:END -->
