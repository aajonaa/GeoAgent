---
id: GEO-5
title: 建立专业工具可用性与交接清单
status: In Progress
assignee: []
created_date: '2026-10-10 06:14'
updated_date: '2026-10-24 08:03'
labels:
  - proposed
  - tools
milestone: m-1
dependencies:
  - GEO-1
priority: medium
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
工具总数、注册数、依赖就绪数和独立验收数曾混用，需要同一版本下的清楚统计和受阻原因。本卡不预设数量。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 分别统计登记、注册、依赖就绪和独立调用通过数
- [ ] #2 受阻工具列出原因而非占位充数
- [x] #3 Schema、单位、约束、错误处理及 Skill 引用一致
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-10-24: Candidate has 220 professional tools / 47 Skills; 1,034 unique actual test cases passed (historical positive records plus nine repaired nodes; includes explicit mocked protocol controls). Preparing isolated publication from 7e0e66b; unrelated MemoraX and memory changes retained. Deployment and browser acceptance are not yet complete.

2026-10-24: Deployed on new A100: 220 professional + 12 runtime tools = 232 registered tools, 47 Skills, zero unavailable Skills. Fresh tests on preserved automatic-memory live baseline: 285 actual call-phase passes including 220 native tool cases; no skips/failures. Tool source commit 5843d38cd848931c1d93be00fe15f88ad407c099. Users, model profiles and paused tasks preserved; no model/retrieval/GPU services restarted. Browser acceptance remains blocked by saved origin permission; receiving-lab/model-workflow acceptance not claimed. 15 source projects remain outside this tool union. Deployment and gate receipts: docs/releases/earth-tools220-*.json.
<!-- SECTION:NOTES:END -->
