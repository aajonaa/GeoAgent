---
id: GEO-13
title: P2.5A - Three-way source integration and configuration composition
status: Done
assignee: []
created_date: '2026-11-08 04:55'
updated_date: '2026-11-08 05:06'
labels: []
dependencies: []
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Independent source integration only. No migration, service startup, model/SMS or deployment. Trusted snapshot Base, Dev c741, Prod 8b46.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Production capacity delta precisely integrated while preserving P2
- [x] #2 Static and isolated pure-unit checks have current-source evidence
- [x] #3 Configuration, provenance, risks and final manifest delivered
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Coded: exact production capacity.py and five reviewed server blocks onto independent Dev c741 copy. All P1/P2 and common source/test files retained. Verified: 247 Python AST parses, 14 static groups, 23 pure capacity units, read-only dependency/network namespace, two-sided whitespace/diff and provenance checks. Static tooling failures preserved; inherited two SyntaxWarnings unchanged. Not tested: app startup, migration/recovery, API/browser, HITL reproduction, model/SMS/load. Three historical HITL failures retained for P2.5B. Released: no. Deployed: no. Production, Dev, Base and original candidate protected. Docs and config templates outside app. Stop before P2.5B.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed - Source Integrated, Static Verified. Full source hash in evidence/P2-05A/integrated-manifest.json outside app. No deployment or full integration claim.
<!-- SECTION:FINAL_SUMMARY:END -->
