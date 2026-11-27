---
id: GEO-23
title: 无未完成工具的已终态任务不再阻塞服务恢复
status: Done
assignee:
  - '@QoderCN'
created_date: '2026-11-27 01:22'
updated_date: '2026-11-27 01:53'
labels:
  - release-0.28
dependencies: []
references:
  - >-
    deployed-build:dca122c794ac1422726afa25354a0af21612a061b80eee6f14d8251cd455dbac
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-recovery-settled-20261127/deployment.json
  - >-
    C:/Users/jona/OneDrive/Documentos/ChatGPT/新一代人工智能项目/output/orebogao-recovery-settled-20261127/recovery-acceptance.json
  - 'git-commit:33457d841ede68d9a170d3d34ff6efa5156edc56'
modified_files:
  - geological_agent/team/recovery.py
  - tests_local/test_recovery_settled_terminal.py
priority: high
type: bug
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
生产重启时，12 条已持久化为 stopped 且没有进程覆盖记录的任务被永久隔离；这些任务的历史工具调用均已返回。恢复逻辑需要区分“终态已结算且无未完成工具”和“外部资源仍未知”，避免后续发布无法启动。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 已结算且无进程覆盖的终态任务，在所有工具都有结果后恢复为 reconciled
- [x] #2 存在未完成工具、终态不匹配或仍有进程覆盖的任务继续隔离
- [x] #3 候选与安装后回归通过，公网服务恢复且后续 GEO-22 发布不被阻塞
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
coded：终态恢复仅在 owner 已确认死亡、恢复证据 phase=settled、terminal_status 与 SQLite 一致、无 process_coverage，且所有 tool_start 都有对应 tool_result 时放行；未完成工具、终态不匹配或仍有进程覆盖的任务继续隔离。
verified：A100 隔离候选与安装后各通过 5 项新恢复回归、29 项终态恢复 API、18 项团队安全回归，共 52 项。生产实测 12 条此前阻塞的 stopped/settled 无进程覆盖记录全部 reconciled，quarantined=0，recovery/model_resources/process_resources readiness 均为真。
released：0.28 版本记录已创建；Git tag/Release 未创建。
deployed：0.28 / dca122c794ac，完整源码 dca122c794ac1422726afa25354a0af21612a061b80eee6f14d8251cd455dbac。公网 / 返回 200、/api/me 返回 401，发布头一致。回滚备份 /data/wangjian/oresage-retrieval-release-20261114/recovery-settled-ab72ec607b。
Git 完成：功能与测试提交 33457d841ede68d9a170d3d34ff6efa5156edc56 已推送 origin/codex/orebogao-geo-ux-global-state，git ls-remote 核对远端尖端一致。本条完成回执通过独立 Backlog 文档提交推送。
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
GEO-23 已完成并上线 0.28：已结算且无未完成工具的终态任务不再阻塞服务恢复，12 条生产阻塞记录全部 reconciled，隔离保护未弱化；候选/安装后 52 项回归与公网健康检查通过，功能提交 33457d8 已推送，回滚备份保留。
<!-- SECTION:FINAL_SUMMARY:END -->
