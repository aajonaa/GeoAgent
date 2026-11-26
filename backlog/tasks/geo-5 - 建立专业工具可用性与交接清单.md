---
id: GEO-5
title: 建立专业工具可用性与交接清单
status: In Progress
assignee: []
created_date: '2026-10-10 06:14'
updated_date: '2026-10-25 15:52'
labels:
  - proposed
  - tools
milestone: m-1
dependencies:
  - GEO-1
priority: medium
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
工具总数、注册数、依赖就绪数和独立验收数曾混用，需要同一版本下的清楚统计和受阻原因。本卡不预设数量。
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 分别统计登记、注册、依赖就绪和独立调用通过数
- [ ] #2 受阻工具列出原因而非占位充数
- [x] #3 Schema、单位、约束、错误处理及 Skill 引用一致
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-10-24: Candidate has 220 professional tools / 47 Skills; 1,034 unique actual test cases passed (historical positive records plus nine repaired nodes; includes explicit mocked protocol controls). Preparing isolated publication from 7e0e66b; unrelated MemoraX and memory changes retained. Deployment and browser acceptance are not yet complete.

2026-10-24: Deployed on new A100: 220 professional + 12 runtime tools = 232 registered tools, 47 Skills, zero unavailable Skills. Fresh tests on preserved automatic-memory live baseline: 285 actual call-phase passes including 220 native tool cases; no skips/failures. Tool source commit 5843d38cd848931c1d93be00fe15f88ad407c099. Users, model profiles and paused tasks preserved; no model/retrieval/GPU services restarted. Browser acceptance remains blocked by saved origin permission; receiving-lab/model-workflow acceptance not claimed. 15 source projects remain outside this tool union. Deployment and gate receipts: docs/releases/earth-tools220-*.json.

2026-10-24: Started GitHub expansion for geology, mineral spectroscopy and geochemistry. Existing release is 220 professional tools / 47 Skills. New operations require pinned upstream source, handoff schemas, provenance, CPU numerical tests and native registration evidence. Not yet deployed.

2026-10-25: Added nine GitHub scientific operations from Spectral Python, pyrolite and mplstereonet, plus three Skills. Candidate catalog 229 professional / 50 Skills. Original 220 definitions and examples retained with canonical hash checks. Isolated A100 r1 failed before numerical tests due upstream pyrolite 0.3.8.post1 importing nonexistent Matplotlib Norm; preparing compatible 0.3.7 with exact dependencies. No service switch or GPU use.

GitHub mineral intake: latest literature-fix baseline CPU regression 292 passed, 0 failed, 0 skipped; 229 professional native operations, 50 Skills. Nine additions from Spectral Python, pyrolite and mplstereonet. GPU and model calls disabled. Deployment pending; browser origin permission still blocked.

Deployed github-minerals-20261025-r3 on A100: 229 professional tools + 12 runtime tools = 241 registered tools, 50 Skills, none unavailable. Preserved latest literature/MemoraX baseline, accounts, model profiles and paused tasks; other services unchanged. Fresh CPU tests: 292 passed. Source commit dbf9f0b. Browser acceptance pending saved origin permission; not claimed as passed.

2026-10-25 NEW USER SCOPE: at least 101 ADDITIONAL genuine professional operations beyond deployed229 (target120). Four disjoint source-authoring groups: geophysics30, remote30, geology30, spatial30. Upstream official provenance/license, semantic deduplication, AI Lab schemas/units/errors, independent numeric tests, native registration and isolated CPU acceptance required. Candidates, source implementations, verified, deployed and lab-submitted counts must remain separate. Existing production229/50 remains unchanged until a new gate passes. No GPU use, no placeholder/count padding.

2026-10-25 expansion r1: merged 120 authored operations into an independent A100 CPU candidate (229+120=349 professional tools; 70 Skills). Initial suites: 286 passed/2 failed plus 93 passed/2 failed; subtest counts tracked separately, not as tool counts. 17 missing pinned wheels installed only in private stage. Shape, dtype, terminal-routing and test-provenance failures remain; independent review also flags scientific-domain/upstream defects, georeferencing loss and one unresolved semantic duplicate. User approval requested for repairs. No newly verified count claimed; no deployment/push/GPU use. Evidence: catalog/source_delivery/github-expansion-20261025/round1-acceptance.json and tests_local/expansion-release-20261025-r1.

2026-10-25 r1 native runtime follow-up: all 120 newly authored operations exercised through existing AgentRuntime/ToolExecutor native cases; 118 passed, 2 failed (MatchedFilter shape; CIPW integer dtype), 26.24s. This is NOT 118 scientifically accepted operations; existing review and numeric findings remain gates. Research found PyFlwDir 0.5.12 for Strahler, Equinor rock-physics-open 1.0.1 for self-consistent moduli, unreleased immutable APSG fix for Bingham, and spectral sensor-band resampling as a genuinely distinct replacement for duplicate histogram mapping. Full Johnson stiffness+stress and full-domain pyrolite CIPW remain unresolved. No fixes applied pending user decision, no deployment/push/GPU. Evidence: native-runtime-round1.json and upstream-resolution-proposals.json.

2026-10-25 r1 baseline compatibility: all 229 original native tools plus catalog/discovery/path/cache gates executed with the new private dependencies. 243 passed, 1 failed (ObsPy requires SQLAlchemy<2 but candidate adds2.1.6). Same candidate source and old dependency paths pass the failing tool (1passed), confirming a candidate dependency regression. APSG declares SQLAlchemy without a version bound; propose preserve original1.4.54 and retest, isolate only genuinely conflicting versions. No production changes. Unified repair decision still pending; all current tests and read-only research are terminal. Evidence: baseline-regression-round1.json and preserved raw logs.

2026-10-25 r2: user approved unified adapter/georeferencing/domain/test/dependency repairs. Private candidate preserves SQLAlchemy 1.4.54; APSG 2.0.6 and ObsPy 1.4.2 import together. Reused 16 verified wheels; privately added PyFlwDir 0.5.12, rock-physics-open 1.0.1 and tmatrix 1.2.0 with official hashes and dependency checks. Scientific-defect and duplicate candidates are not counted. Target remains at least 101 genuinely new accepted operations; original 229 regression required. No production changes, deployment, push or GPU use.

2026-10-25 r2 CPU results: 117 additional native calls passed; 229 original operations plus metadata 244 passed; contracts 237 passed; scientific groups 153 passed plus 692 subtests. Total 751 passed, no unexpected failures; 1 retained expected-failure diagnostic for unregistered StressAnisotropy blocks the all-skips gate. Candidate346 professional tools/70Skills; upstream Bingham/CIPW/Stress candidates not counted. All r1 evidence preserved. User confirmation requested only for separate historical diagnostic reporting and README inequality typo. No deployment, push or GPU use. Evidence: catalog/source_delivery/github-expansion-20261025/round2-acceptance.json.

2026-10-25 r3 CPU acceptance complete: exact blocked StressAnisotropy node reported separately as 1 expected failure, NOT a pass/tool; original diagnostic and assertions unchanged. README prose corrected to match 1/Gwet >= 1/Ghigh > 0. Formal 751 passed, zero failures/errors/skips, plus 692 passed scientific subtests; 9 reporting gate controls passed locally and on A100. New117 native operations and original229+metadata all passed. Candidate346 professional tools/70Skills. Old r1/r2 evidence preserved. No algorithms changed this step, no deployment/push/GPU. Final summary: catalog/source_delivery/github-expansion-20261025/round3-acceptance.json.

2026-10-25: The accepted 117-operation expansion was merged without replacing unrelated work. Exact accepted hashes for 289 changed files match the Git index. Full CPU regression repeated at the production release path: 751 formal cases passed, zero failed/errors/skipped; the known StressAnisotropy diagnostic remains separate and not counted. Candidate: 346 professional tools, 70 Skills, 12 runtime tools. Deployment and push pending the final switch guard. No GPU or model calls.

2026-10-25 released/deployed: source7466cfa pushed to codex/earth-tools220-20261024. New A100 switched to github-expansion346-20261025-r1 after zero-active-run and exact old/new-source guards. Backend confirms346 professional operations,70Skills,12runtime tools,358registered,0unavailable Skills,PostgreSQL connected. Saved accounts/model settings/conversation-file counts preserved and other services unchanged; noGPU. Browser acceptance remains pending saved site denial; receiving-lab delivery approval is not claimed. Four separate research inventories target additional distinct operations toward500+; research is not counted as available.

2026-10-25 research follow-up:102 proposals recorded separately (geophysics30,geology22,remote20,spatial30),zero implemented or accepted from that research set. Unique-ID/research-status checks passed against deployed346; this is not numerical or semantic acceptance. 501 professional operations requires155 further accepted additions. Even if all102 pass,total448;at least53 more distinct candidates are still needed. Research source inventories and unresolved dependency/license/numeric-oracle risks are retained; no runtime registration or service change.
<!-- SECTION:NOTES:END -->
