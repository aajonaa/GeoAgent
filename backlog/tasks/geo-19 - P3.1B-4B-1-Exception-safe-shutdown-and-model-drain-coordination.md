---
id: GEO-19
title: P3.1B-4B-1 - Exception-safe shutdown and model drain coordination
status: Done
assignee: []
created_date: '2026-11-09 05:09'
updated_date: '2026-11-09 07:19'
labels: []
dependencies: []
modified_files:
  - geological_agent/team/server.py
  - geological_agent/team/shutdown.py
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Frozen B4A 8c8960cc. D07 model drain and D09 exception-safe shutdown only. Preserve B1/B2/B3/B4A; no schema, production, external tool/cgroup cleanup or forced Provider termination. Reproduce, design before code, fault injection and fresh regressions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Frozen source, dependencies and resource isolation verified
- [x] #2 Before/after terminal faults and fresh regressions recorded
- [x] #3 Reproducible defects, recommendations and final protection reports delivered
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded: Yes. Verified: Yes on final v6 business source (component SHA in evidence/P3-01B4B1/implementation-v6.json). Released: No. Deployed: No.
Shutdown135/135, B1 66/66, B2 96/96, B3 96/96, B4A99/99, existing336/336 (HITL9 included), related121/121, API13/13, Chromium95/95, originalD09 3/3. Original strictD07 0/3 retained as B4C/old conservative cold admission503, no skip/xfail.
Protected final integrity and6MD/9JSON report closure follow; D08 external tools/cgroups B4B2 and Provider strict termination B4C remain Open. No production mutation, GeoGPT/SMS or5account real load.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed — Shutdown Orchestration Verified. Six required Markdown and nine required JSON delivered; protection checks passed. D07 finite drain/quarantine and D09 exception isolation verified. External Tool Cleanup Pending P3.1B-4B-2; Provider Bounded Termination Pending P3.1B-4C. Original strictD07 three failures retained. Coded/Verified yes; Released/Deployed no. Final app manifest is computed after this ledger update; no commit/push.
<!-- SECTION:FINAL_SUMMARY:END -->
