# Xiaoyu Skill release, 2026-10-29

The first release at commit fe0c8d775d9cbf4c9d6333a775ed1eb51b2c11c4 was
deployed to the A100 GeoAgent service and pushed to
codex/xiaoyu-skills-release-20261029. The current live literature, PDF reader,
knowledge graph and MemoraX source files were retained in the preceding commit
0bafdb4c31a0e6287bf4cd616f1745cc23308281.

## Scope and counts

110 input archives contained 132 Skill documents; content deduplication produced
90 added Skills, with all 42 duplicate occurrences retained in source provenance.
The runtime now has 187 Skills, 457 professional operations and 13 runtime tools
(470 registered tools total in the live configuration). SkillReadResource is the
only new runtime utility. It lists, reads and prepares hash-verified resources;
it does not execute source scripts or install dependencies.

## Evidence

The original isolated A100 run executed 141 tests: 139 passed, one historical
document-contract test failed, and the frontend test failed because Node was
absent from that test process's PATH. Repeating the frontend test with the
already-installed Node 24.21.0 passed. The first deployment therefore had 140
unique passing tests and one explicitly retained historical document failure.
All 107 new Skill checks passed. No failure was silently skipped.

The deployment compared live and candidate source hashes, preserved the account,
conversation, file and model/memory state fingerprints, and verified other
application, model and retrieval service identities. GPU use and model calls
were disabled for this work. Backend acceptance returned 187/457/470 as above.
The browser also displayed these counts; searching xiaoyu returned 90 cards,
and the new pyrolite Skill detail rendered its instructions and linked tools.

## Documentation repair

The 20 old Skill documents lacked required handoff/availability sections. This
follow-up adds registry-bound callable descriptions and explicit availability,
while preserving the original scientific limitations and historical records.
Workflow and laboratory validation remain not_run. The regression assertion now
requires zero legacy document failures; the original 20-failure report remains
unchanged under catalog/imports/xiaoyu/baseline-diagnostics.json.

This is not an AI Lab certification or scientific validation of all 90 imported
workflows. The bundled 185 Python scripts were syntax-checked, not executed.

MemoraX's updated workbench URLs and API-origin distinction are documented in
docs/memorax-workbench-20261029.md. No account preferences, credentials, remote
memory records or API origin were changed.

Detailed local evidence is retained in
D:\oresage-xiaoyu-release-20261029 and the A100 release directories. Failed
attempts remain preserved alongside successful retests.
