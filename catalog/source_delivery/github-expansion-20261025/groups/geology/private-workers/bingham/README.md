# Bingham immutable-source procurement and fixed CPU binding

Status: BLOCKED / NOT REGISTERED / NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.
No environment has been created, no package acquired or installed and no scientific test run here. This profile contributes zero active tools.

## Exact procurement

Use `requirements-source.txt` only for this separate environment. The APSG source is the immutable archive at commit `44f9dde66e2e36417e09aebffd9992756705d7ab`:
https://github.com/ondrolexa/apsg/archive/44f9dde66e2e36417e09aebffd9992756705d7ab.zip

Its source declares version 2.1.0, but this is an UNRELEASED commit, not evidence for a published `apsg==2.1.0`. Published APSG2.0.6 remains pinned for all 11 active APSG operations. SQLAlchemy remains 1.4.54 in both environments. Scientific pins and parent-confirmed application constraints are explicit in the requirements file. ObsPy1.4.2 is not required by this single-tool kernel and need not be copied into it; the existing parent environment is unchanged.

The upstream build system requests setuptools>=61.0. Parent must pin the actual approved build toolchain, freeze remaining transitive utilities, create the offline wheelhouse, and record source-archive/wheel SHA256 before activation. Those artifacts were not acquired here; no invented archive hash or build version is supplied.

## Fixed environment binding, not request-time selection

The proposed fixed prefix is `catalog/source_delivery/github-expansion-20261025/groups/geology/private-workers/bingham/.venv`, relative to the parent's candidate checkout. Trusted configuration resolves either `Scripts/python.exe` on Windows or `bin/python` on POSIX, as listed in `worker-profile.json`. No tool argument can choose an interpreter, environment, module, function or code.

1. Parent binds ONLY GeoAPSGBinghamAxialConfidence to that interpreter, in isolated Python mode, with no system site-packages, PYTHONPATH or user site inheritance.
2. The entire decorated call, including dependency checks and provenance construction, must execute in that interpreter. A subprocess called after the main decorator checks apsg==2.0.6 does not meet this requirement.
3. The parent supplies a fixed trusted worker entry, scoped single-tool catalog, bounded request/response transport and CPU-only execution controls. No runtime network/download/install, GPU use or fallback to the main interpreter is permitted.
4. Parent enforces immutable source identity from acquisition/build receipts and installed files, not merely the source's self-reported version. Commit, archive/wheel hashes, interpreter and installed-package provenance must be truthful. The current package-release-only metadata cannot be relabeled as a published 2.1.0.
5. Only after independent scientific acceptance and a qualified adapter does the parent enable the route and add this tool back to contributions. The current public function deliberately fails closed.

The current contribution does not implement parent-owned dispatch or modify the SDK. The profile is disabled, not a claim that the binding exists.

## Upstream fix and license evidence

[Maintained fixed confidence kernel](https://github.com/ondrolexa/apsg/blob/44f9dde66e2e36417e09aebffd9992756705d7ab/src/apsg/feature/_distributions/_axial.py) now uses axial fourth moments and saturates nonidentifiable directions at 90 degrees rather than the old collapsing expression.
[Public Vector3Set API](https://github.com/ondrolexa/apsg/blob/44f9dde66e2e36417e09aebffd9992756705d7ab/src/apsg/feature/_container/_vectorsets.py) calls that maintained kernel and also fits a Bingham distribution; checking only the low-level helper is insufficient.
[Immutable change comparison](https://github.com/ondrolexa/apsg/compare/f9f45a52d60521ba37f326a85645df3dee74272e...44f9dde66e2e36417e09aebffd9992756705d7ab) documents the upstream refactor.
[MIT license](https://github.com/ondrolexa/apsg/blob/44f9dde66e2e36417e09aebffd9992756705d7ab/LICENSE) is preserved in LICENSE-APSG.txt. These are reviewed upstream sources, not locally passing scientific evidence.

## Independent acceptance gap

`acceptance-plan.json` records identifiability/rotation invariants and missing coverage/nondegenerate numeric evidence. The r1 angle expectation is rejected because it repeats the faulty expression. No distinct-axis restriction, F=0-style domain narrowing, local kernel patch or formula replacement is used to force a pass.
