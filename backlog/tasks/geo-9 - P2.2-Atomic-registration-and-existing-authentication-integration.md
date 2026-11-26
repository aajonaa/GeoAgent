---
id: GEO-9
title: P2.2 - Atomic registration and existing authentication integration
status: Done
assignee: []
created_date: '2026-11-07 16:50'
updated_date: '2026-11-07 17:01'
labels: []
dependencies: []
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Continue exact P2.1 workcopy; single-connection registration commits account/profile/invite/OTP/event atomically, then existing login. Public registration default disabled. No production, frontend or provider deployment.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Registration facts commit or rollback together, incorrect OTP attempts persist
- [x] #2 Real multi-connection/process races, SQL denials and Session/response failures have evidence
- [x] #3 Old public bypass blocked; existing auth compatible; Mock only and no production modifications
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded: seven source/test files; transaction-aware Store insert, atomic registration service and existing HTTP/auth integration. Verified: 192 pytest (134 rerun plus 58 new), 13 legacy API smoke, actual SQLite rollback/CAS/COMMIT denial and independent connection/process races. Initial test observer threading failure retained and corrected. Reports and sanitized evidence delivered. Released: no. Deployed: no. Real SMS: not configured/not tested. No frontend, task concurrency or public routing changes. Stop before P2.3.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed - Mock Registration Verified in independent P2.2 workcopy; six registration facts atomic, existing login after commit. No production deployment; wait for separate P2.3 prompt.
<!-- SECTION:FINAL_SUMMARY:END -->
