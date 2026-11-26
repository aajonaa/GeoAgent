---
id: GEO-21.5
title: 科研证据链与成果版本
status: Done
assignee: []
created_date: '2026-11-26 14:52'
updated_date: '2026-11-27 06:19'
labels:
  - frontend ux
dependencies: []
parent_task_id: GEO-21
priority: medium
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
成果已有 generation 和哈希快照，但结论、来源、图件与历史版本之间缺少可操作连接。增加证据定位、图件元数据、版本比较和恢复入口。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 关键结论可定位到支持或反驳来源及上下文
- [x] #2 图件展示来源、坐标、单位和比例尺等已记录元数据，不推断缺失值
- [x] #3 历史 generation 可查看、比较、下载并恢复为新版本
- [x] #4 跨账号和跨会话文件访问仍被拒绝
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
GEO-21.5 已完成：0.27 / 390d7f6fe5bd，候选与安装后定向测试 124 通过、2 跳过，版本/证据/权限、旧空成果兼容、逐波段单位及 1440/390 公网回放和资产哈希通过；功能提交 3c7b4a9 已推送且远端尖端一致。引用仅展示已保存原文与结论上下文，支持或反驳需人工判断；图件缺失元数据不推断；恢复创建新快照并保留历史版本。
<!-- SECTION:NOTES:END -->
