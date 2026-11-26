---
id: GEO-8
title: P2.1 - Advisory invitation and SMS verification service
status: Done
assignee: []
created_date: '2026-11-07 15:59'
updated_date: '2026-11-07 16:07'
labels: []
dependencies: []
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Continue the verified P1.2 workcopy; implement invitation reads, configured phone plans, keyed OTP, transactional send reservations, mock/disabled/provider boundary and advisory APIs. Do not consume or register.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Invitation and OTP checks do not create accounts, sessions or final consumption
- [x] #2 Durable quotas, attempts, isolation and privacy have real tests
- [x] #3 Required documents and provider readiness accurately distinguish Mock from real sending
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded: five new service/config/provider/API modules, two test files, optional create_app routing only. Verified: 134 pytest and 13 legacy API checks; structured Mock API/security evidence, unchanged baseline/config/services. Released: no. Deployed: no. Real SMS: not configured/not tested. Final invitation/OTP consumption and registration remain P2.2.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed - Mock-Verified in independent P2.1 workcopy. Reports and exact evidence delivered; stop before P2.2.
<!-- SECTION:FINAL_SUMMARY:END -->
