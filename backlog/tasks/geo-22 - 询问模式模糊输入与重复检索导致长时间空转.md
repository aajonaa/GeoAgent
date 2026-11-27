---
id: GEO-22
title: 询问模式模糊输入与重复检索导致长时间空转
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-27 00:18'
updated_date: '2026-11-27 02:18'
labels:
  - release-0.29
dependencies: []
references:
  - >-
    deployed-build:0c711c65a9b547070580beb609ea0876dc1bc705842c3f7170dfe01dc0546117
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ask-mode-guard-20261127/deployment.json
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-ask-mode-guard-20261127/live-replay.json
  - 'git-commit:38e3465f45fc9bb15dd070a2a0bff0767375218f'
modified_files:
  - geological_agent/agent/runtime.py
  - tests_local/test_compact_intent_review.py
  - tests_local/test_postgres_context.py
priority: high
type: bug
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
生产询问模式对“这个智能体”执行 44 次 context_search 和 4 次 context_read，耗时 16 分 10 秒后才要求澄清。根因是只读模式未执行既有意图检查，重复检索提示没有终止条件，且团队任务关闭了模型轮次上限。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 模糊或缺少明确目标的询问在执行任何历史检索前直接提出一句澄清
- [x] #2 询问模式重复返回相同检索证据时停止检索，并基于已有信息作答或澄清
- [x] #3 正常询问与执行模式行为不回退，候选和安装后测试通过
- [x] #4 公网用同一模糊输入回放，确认不再出现数十次工具调用和十几分钟空转
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
启用只读模式的既有意图检查；为只读检索增加重复证据硬停止；补充回归测试后按现有发布链验证、部署和推送。
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
coded：询问模式启用既有 assess_task_intent 意图检查；模糊输入在历史检索前直接 needs_input。只读 context_search/context_read 第一次检测到重复 unchanged 证据即设置 read_only_retrieval_exhausted，下一请求 tool_choice=none 且清空工具，强制基于已有观察回答或澄清；人类补充输入后清除停止标记。
verified：A100 隔离候选与安装后各通过 89 项定向回归（6 意图/预算、1 重复检索硬停止、47 计划 API、4 检索进度/重定向、2 意图协议恢复、29 终态恢复 API）。真实 Chrome 公网回放三例通过：vague_ask 22.0s needs_input 0 工具，clear_ask 40.15s completed 0 工具，clear_agent 27.16s completed 0 工具，page_errors=[]。
released：0.29 版本记录已创建；Git tag/Release 未创建。
deployed：0.29 / 0c711c65a9b5，完整源码 0c711c65a9b547070580beb609ea0876dc1bc705842c3f7170dfe01dc0546117。公网 / 200、/api/me 401，发布头一致。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/ask-mode-guard-15698fafc9。
Git 完成：功能与测试提交 38e3465f45fc9bb15dd070a2a0bff0767375218f 已推送 origin/codex/orebogao-geo-ux-global-state，git ls-remote 核对远端尖端一致。本条完成回执通过独立 Backlog 文档提交推送。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GEO-22 已完成并上线 0.29：询问模式先做意图检查，模糊输入直接澄清；重复历史检索硬停止并强制作答/澄清。公网同一“这个智能体”从 16 分 10 秒、48 次工具调用降为 22 秒、0 次工具调用；清晰询问与执行模式不回退，候选/安装后 89 项回归和真实 Chrome 三例通过，功能提交 38e3465 已推送。
<!-- SECTION:FINAL_SUMMARY:END -->
