---
id: GEO-15
title: P3.1B-1 - Model slot ownership and cancellation fix
status: In Progress
assignee: []
created_date: '2026-11-08 10:41'
updated_date: '2026-11-08 11:34'
labels: []
dependencies: []
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Frozen P25B3d677. Model slot ownership fixes D02/D03 only. Reproduce before edits, explicit invariants, minimal business patch, deterministic model faults and full regression; no production or real provider.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Frozen source, dependencies and resource isolation verified
- [x] #2 Before/after model faults and336 regression evidence recorded
- [x] #3 Reproducible defects, recommendations and final protection reports delivered
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded:server.py only, private per-request lease of existing semaphore; D02 probe running/pending cancellation and submit compensation; D03 invoke constructor/start handoff. Verified:before9failed, after9targetpass, new66pass, legacy-model66pass(incl3sourceN/A), existing336pytestpass incl capacity23/integration12/HITL9, API13pass. Out-of-scope task75observations45pass30fail;restart12/6pass6fail retained. Raw original probe unsafe-overlap synchronization fails; adapter preserves safety AST and adds429/retry checks. Initial F11 bad-field expectation and legacy controller450s wrong -k selection retained; explicit model66 rerun and missing task6 completed, no per-case timeout extension. Metadata summary hidden-path failure corrected using own copied inputs, logs retained. Status:Partially Completed. Model slot ownership safe in controlled scope; no reliable hard cancellation or total deadline for synchronous/real Provider; do not claim full cancellation safety. D02/D03 Fixed and Verified; other8Open. Production app/model service changes observed, broker attribution unknown; this task issued no protected-service mutation commands. Released:no. Deployed:no. Stop before B2/P3.2.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Partially Completed - model slot capacity verified; bounded Provider termination not guaranteed. Two defects fixed; eight remain Open; no deployment.
<!-- SECTION:FINAL_SUMMARY:END -->
