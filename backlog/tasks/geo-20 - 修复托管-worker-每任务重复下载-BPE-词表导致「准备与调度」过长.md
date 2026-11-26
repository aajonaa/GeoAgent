---
id: GEO-20
title: 修复托管 worker 每任务重复下载 BPE 词表导致「准备与调度」过长
status: Done
assignee: []
created_date: '2026-11-26 08:13'
updated_date: '2026-11-26 08:32'
labels:
  - runtime
  - latency
  - release-0.20
dependencies: []
priority: high
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
RunProgress 的 runtime 阶段（UI 标签「准备与调度」）在第一次模型请求前包含了 tiktoken 词表下载。tiktoken 0.12.0 默认缓存位于 gettempdir()/data-gym-cache，而 trusted_process.worker_command 为每个 run 挂载 --tmpfs /tmp 并强制 TMPDIR=/tmp，缓存每次归零；bwrap 未 --unshare-net，于是每个任务在 worker 内重新拉取 cl100k_base 与 o200k_base 共 5.3 MB。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 TIKTOKEN_CACHE_DIR 未设置时使用 HOME 下持久目录；运维显式值与只读 HOME 行为保持原样。
- [x] #2 全新 tmpfs 场景首次估算不再走网络，tokens 与 count_method 与基线一致。
- [x] #3 tests_local 相关子集基线与候选失败集合一致。
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
实现 geological_agent/context_budget.py 新增 _pin_tokenizer_cache()。提交 47197a2，分支 codex/orebogao-geo-tiktoken-cache，基线 90a05b3。测试 tests_local/test_tokenizer_cache.py 共 6 项。证据目录 output/orebogao-tiktoken-cache-20261126/。对照：基线全新 tmpfs 89.488/137.714/146.687 秒，候选第二个 run 起 0.508/0.509 秒；部署后用生产 app 目录与真实 worker HOME 复测 0.510/0.508 秒。子集基线 45 failed/173 passed/7 skipped，候选 45 failed/179 passed/7 skipped，差集为空。发布 0.20 / c4f4e85e92c4，回滚备份 /data/wangjian/oresage-retrieval-release-20261114/tokenizer-cache-7e603f5cb6。
线上真实任务复验：用受控验收账号 hitl_review（member）在公网以询问模式跑通 run 47c13cdcebcd457f9b34fc8704066dad，终态 completed，总 34.61 秒，run activity 的 totals_seconds.runtime（即「准备与调度」）为 7.72 秒，对照修复前同一阶段 21.1 秒。回执 live-run.json，脚本 verify_live_run.py。残留约 8 秒为 broker 准入、bwrap 与 create_agent 装配 474 工具/191 技能的既有开销，不在本条目范围。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
已发布并线上复测。发布记录 release_record.task 写作 GEO-50，实为本条目，入口脚本 NOTES 笔误已在批次 verification.json 说明。
<!-- SECTION:FINAL_SUMMARY:END -->
