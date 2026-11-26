---
id: GEO-7
title: P1.2 - Backward-compatible database migration and minimal DAL
status: Done
assignee: []
created_date: '2026-11-07 14:31'
updated_date: '2026-11-07 14:39'
labels: []
dependencies: []
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement the approved P1.1 schema only in independent candidate test databases. Preserve production and P0.2 running baseline. No registration service or real SMS.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Frozen five-table and three-column expansion is idempotent and rollback-safe
- [x] #2 Minimal DAL participates in caller-owned transactions without commits
- [x] #3 Existing tests, new constraints, old-code API and independent recovery have real evidence
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded: six new source/resource/test files; no old business source changes. Verified: 78 pytest and 13 old-code API checks; isolated backup/migration/recovery and 15 acceptance gates. Released: no. Deployed to running candidate/production: no. Reports and exact commands delivered in ../docs/implementation and ../evidence/P1-02. P1.2 does not implement or validate the P2.2 registration transaction.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed P1.2 in the independent candidate workcopy only. Preserved the original candidate baseline and production. Waiting for a separate P2.1 instruction.
<!-- SECTION:FINAL_SUMMARY:END -->
