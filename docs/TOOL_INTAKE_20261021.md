# Tool-only integration

Ten supplied implementations merged into the current production source snapshot.
126 professional tools, 34 Skills; runtime utilities are counted separately.
The 133 intake candidates are not executable tools.

Public entrypoints accept schema-conforming dictionaries or JSON objects. Native ToolExecutor uses the same functions.
Array length, finite values, ranges, grid workload, fit evaluations, seeded permutation workload, and SEG-Y file/preview size are bounded.
Errors use ScientificToolError with code/message/retryable. Native errors preserve these fields.
Results include declared/explicitly unspecified units and source/version/input/implementation provenance. No units or CRS are silently converted.
SEG-Y native paths remain workspace-relative. Existing input snapshots and artifacts are preserved.

The receiving AI Lab must still approve the exact official protocol, project adapter redistribution license, and platform acceptance.
Do not interpret registration or historical tests as full model workflow/scientific certification.
No deployment, commit, push, paid model call, or GPU use is performed by this merge.
