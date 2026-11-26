---
id: GEO-16
title: P3.1B-2 - Task startup compensation D01 D04
status: In Progress
assignee: []
created_date: '2026-11-08 15:15'
updated_date: '2026-11-08 16:11'
labels: []
dependencies: []
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Frozen P31B1 572a7ae3. Task startup D01/D04 only, retain D02/D03. Reproduce before edits, explicit invariants, minimal business patch, deterministic model faults and full regression; no production or real provider.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Frozen source, dependencies and resource isolation verified
- [x] #2 Before/after task startup faults and freshly counted regressions recorded
- [x] #3 Reproducible defects, recommendations and final protection reports delivered
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded:server.py startup claim/abort ownership, constructor/start and trace initialization compensation, per-user pending/HITL recovery, readable startup503; store.py optional preallocated rid and fenced fail_start, schema/finish unchanged. Model lease and paths unchanged. Verified:original18 failed before patch and all18 pass after; final startup96 pass, frontend error contract1pass after1fail, final model66 pass, original141=129pass12knownfail(including model66pass with3sourceN/A), existing336pass including HITL9/capacity23/integration12; API13pass. Final independent restart12=6pass6knownfail; PG stopped. No final fixture errors or skipped/xfail. Initial pilot27pass2fail retained; HITL retry boundary and SQLite fixture corrected. Readable error payload regression fixed and full final tests rerun with fresh roots; earlier results retained. Status Partially Completed: D01 Fixed and Verified, D04 Partially Fixed due continuous DB-unavailable pending running records; D02/D03 retain Fixed and Verified; D05/D06/D07/D08/D09/D10 Open. Pending is explicit503, not durable success; storage recovery and same-user/HITL retry verified. No total Provider deadline/cancellation claim. Evidence external version.json/final-integrity.json pins full source after ledger. Released:no. Deployed:no. No production/frozen/source/service mutation. Stop before B3.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Partially Completed - startup ownership verified; D04 storage-unavailable dependency remains; no deployment.
<!-- SECTION:FINAL_SUMMARY:END -->
