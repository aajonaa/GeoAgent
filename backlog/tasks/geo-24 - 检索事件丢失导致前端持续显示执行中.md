---
id: GEO-24
title: 检索事件丢失导致前端持续显示执行中
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-27 01:58'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
用户报告 context_search 期间前端可能一直显示执行中。排查发现事件渲染异常会先提交 SSE 序号再分发，导致 tool_result/finished 丢失；服务端正常关流后浏览器处于重连态时也不会用终态快照收尾；Experience 终态不清理 running 工具计数。需要保证后端已终态时前端必然收尾，并如实标记未记录结果。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 事件渲染失败不提交序号，可重放或从最后成功序号重新同步，终态不丢失
- [x] #2 SSE 正常关闭或重连时，终态快照关闭流并回填历史；needs_input/stopped/failed 后不再显示工具执行中
- [x] #3 context_search/context_read 有明确检索文案，未返回结果标为结果未记录；候选与安装后回归、真实 Chrome 回放通过
<!-- AC:END -->

## Completion Evidence

- 版本：`0.30`；release：`964c101d6bb9`；完整构建：`964c101d6bb9fa70b633d62d3f52f2213bd000b565230afc6fe0035bb83b8098`。
- 代码提交：`2212417edfa5942b42032fc1ba048f4a3b7bbd93`；已推送至 `origin/codex/orebogao-geo-ux-global-state`，远端分支 tip 与本地 HEAD 一致。
- 候选回归：`experience-regression.js`、`event-resync-regression.js`、`live-ui-regression.js`、`timeline-regression.js`、`terminal-recovery-regression.js` 全部通过；提交前再次运行全部通过。
- 安装后资产哈希：`app.js` = `1e8ed5b6ce0f05fadff693b63087379cfae4eb0c72194bd26f2f4b80870f2cd2`；`images.js` = `3c6e6a5ed89282b2e4a12d09ac95b0eafd72737489fe40874b15370582246487`；`index.html` = `dfcc315c2bf6efe18d11ee7f543c1107ddd338d2ee2fffe7974c4df982d24151`。
- 公网检查：`/` 返回 `200`，`/api/me` 返回 `401`，发布头均为 `964c101d6bb9`。
- 真实 Chrome 回放（均零工具调用、无页面错误）：
  - 模糊 Ask：run `dff3356317db41bd950ddeaaf2894ffd`，`needs_input`，23.72 秒，答复“你想了解这个智能体的哪些方面？”。
  - 清晰 Ask：run `adc9935cc8464a4b92b7c3c7c1b491ad`，`completed`，49.59 秒。
  - 执行模式：run `5fd0c0a908f34ff5ba2fe718b16de7f1`，`completed`，122.98 秒，答复“执行模式正常”。
- 部署单元：`oresage-p31b4b2b2b1-a0fe4820aecf46a4903baa98a7122c10.service`，PID `931619`；recovery/model_resources/process_resources 就绪标记均为 `true`。
- 回滚备份：`/data/wangjian/oresage-retrieval-release-20261114/event-resync-021b03d86e`。
- 发布窗口事故：维护门开启后的冷启动窗口曾观察到公网 `/` 返回 `502`、`/api/me` 返回 `503`。主机侧确认新单元已 active 且 ready，发布流程随后完成、恢复公网入口；安装资产、终态回放及恢复后的公网健康检查均通过，因此未回滚。该体验问题必须保留为发布流程缺陷，后续发布前应先消除或验证此维护/冷启动窗口，未获明确指示前不再进行生产发布。
- 证据目录：`output/orebogao-event-resync-20261127/`，包含 `build.json`、`candidate-tests.json`、`installed-check.json`、`deployment.json`、`public-check.json`、`live-replay.json` 与 `vague-ask.png`。