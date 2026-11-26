# Remote isolated CPU interface request (proposal, not implemented)

Status: source-only; not integrated, not deployed, not submitted. Model workflow not_run.
This request changes no shared SDK, registry, worker, or accepted bridge profile.

## Minimal parent-owned contract

1. Add an administrator-owned registration_metadata.runtime.isolation_profile_id.
   It is never a model argument, executable path, environment override, or module/function name.
   Resolve it only against the fixed shared profile allowlist.
2. In collection_contracts.operation, resolve this profile before the existing
   dependency guard only for allowlisted isolated tools. Do not remove, rewrite,
   or claim satisfaction of the tool's true requirements in the main interpreter.
   The main interpreter validates its transport/schema dependencies and profile
   integrity, then invokes the fixed child entrypoint.
3. The child uses a trusted internal execution context (not an args field or
   user-controlled environment flag) to avoid recursively forwarding the call.
   It executes the same dependency guard in the interpreter that imports the
   upstream package. Record installed versions, source identities, Python/native
   identities and profile hash. Exact archive pins require reviewed package
   metadata/source receipt, not a fabricated ==version for SCM builds.
4. The fixed child executes the named @operation adapter and returns the existing
   typed data/error envelope plus a file manifest. The main side verifies schema,
   real return code, source/profile/build receipts, strict finite JSON, file
   sizes/hashes, no symlinks/traversal and tool-specific content before copying
   files to the ToolExecutor-managed output directory. Rewrite only artifact
   transport paths, retain both worker and main provenance, rehash copied bytes.
   A child report alone does not certify output contents.
5. Bound stdout/stderr while draining, not after unlimited buffering. Set a
   deadline, hard process-tree cancellation, <=2 threads and all GPU selectors
   empty/none. Isolate HOME, XDG, MPL, NUMBA, temp, locale and caches. No network,
   runtime installs/compilation, arbitrary shell, user executable path, user
   module/function name or user-defined JSON pipeline.
6. Snapshot only declared input files, preserving relative SAFE directory layout,
   full SAFE references and file hashes. Copy mutable MintPy HDF5 inputs into
   per-call private workspaces; never modify original input files. Treat missing
   weather/tide/original sensor metadata as a failure, not a data-generation task.

Proposed successful transport envelope (closed schema to be owned by parent):
status="ok", tool=fixed ID, data=registered output object,
files=[{relative_path, sha256, bytes, media_type}].
Errors use status="error", tool=fixed ID, error={code,message,retryable:false}
and a nonzero exit status. Output artifacts remain inside data under the existing
contract and must correspond 1:1 to transported files. Native/source identity
receipts are administrator bindings, never model-supplied proofs.

## Why native_cpu_bridge.py cannot presently provide this route

- invoke() rejects output_dir before dispatch.
- It explicitly rejects nonempty artifacts/output_sha256.
- Its TemporaryDirectory ends before parent artifact ingestion.
- It captures stdout/stderr without a streaming byte limit and checks size later.
- Its configured thread environment is four, not this task's bound of two.
- A private venv or catalog entry does not repair any of those incompatibilities.

Do not alter accepted profiles or disable existing protections. Prefer one new,
versioned artifact-capable protocol in the parent-owned bridge, leaving old JSON
profiles unchanged. No alternate remote transport is proposed or authorized.

## Local contribution boundary

blocked_support.py contains preflight checks and two unregistered concrete kernels.
There are no placeholder @operation registrations and no executable worker launcher.
Eight candidates remain blocked until the relevant shared path, source/native/data
identity and independent scientific gates actually pass. Local preflight test
results cannot promote them. Source commits/license URLs are evidence, not build,
legal redistribution, receiving-platform certification or scientific acceptance.
