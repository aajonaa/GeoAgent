# Earth Python first integration wave

Eight concrete upstream operations; previous 126 professional definitions and their algorithms are preserved.
All new operations are unverified draft candidate registrations until independent acceptance is complete. No receiving AI Lab certification is claimed.

## Interface

- Native ToolDefinition via the existing canonical source registry, not a text/XML tool adapter.
- Direct Python: function(args={...}) or function(args='JSON object'). JSON-only calls return JSON-serializable objects.
- File-producing calls require output_dir pointing to a new or empty directory. Native execution supplies this directory and registers every file as an artifact.
- The native runtime resolves workspace-relative input paths, snapshots file inputs, and returns workspace-relative generated artifact paths.
- Stable ScientificToolError(code, message, retryable) errors; errors and partial files are not successful results.
- Explicit input/result schemas, units, CRS, file/array/grid bounds and applicable physical assumptions.
- Input content, implementation and output hashes; installed release and reviewed source commit are recorded separately.
- Source reference is the supplied archive HEAD; runtime is a pinned published release. Byte-identical correspondence is not asserted.
- No tool-time dependency installs, network requests, arbitrary expression parameters, fake observations or silent result truncation.

## Acceptance and handoff

Independent source/JSON/native invocation, negative inputs, artifact values, registration, original-tool regression and environment locking are required.
All synthetic test fixtures must be clearly labeled. No model workflow/platform acceptance has yet occurred.
The final receiving-platform contract document and redistribution approval still require confirmation; copied upstream licenses are retained.
