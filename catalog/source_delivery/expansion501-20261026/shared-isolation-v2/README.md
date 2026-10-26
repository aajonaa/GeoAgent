# Isolated CPU bridge v2: bounded source delivery

Status: source-authored; local protocol results are recorded separately. Not deployed,
not submitted, formal eligibility not established, scientific/model/Linux acceptance
not run. The shipped administrator allowlist is EMPTY. No native runtime identities,
license approvals, binary hashes or dependency installations are manufactured.

## Fixed integration contract

Only `registration_metadata.runtime.isolation_profile_id` selects isolation.
The existing decorator resolves the normal catalog and validates input first. Its
minimal hook then invokes this bridge BEFORE the main-interpreter dependency guard.
The fixed child calls the SAME decorated operation; a process-local ContextVar
allows only that tool/spec to reach the unchanged actual child dependency guard.
No environment variable enables this bypass. Old non-isolated behavior is unchanged.

The parent administrator prepares `profiles.json` conforming to
`profile.schema.json`. Paths are absolute; paths in hash maps/manifests are bounded
relative paths. All fields are required and closed. Each profile binds one tool,
module, named decorated callable, actual Python version/prefix/executable hash,
fixed worker hash, canonical catalog, exact dependency lock, reviewed build/license
receipt, explicit source closure, native projects, resource limits and output rules.
Exact source-URL requirements are unsupported: a reviewed installed-version pin and
source identity must be supplied instead. Unsupported/unprepared profiles fail closed.
The source closure includes this bridge, worker, collection_contracts, source_contracts,
scientific_tools, all imported local source/package initializers and the actual adapter.
Receipt booleans are administrator assertions, NOT evidence of receiving-platform
certification. Do not set them true without a real review.

The closed schemas for build/native receipts are in profile.schema.json $defs.
Native projects have {version,root,executable,build_receipt,closure_complete,
files_sha256}; executable/receipt are relative and hash-bound. A native PDAL version
is not a Python pdal distribution version. No user executable, environment, shell,
module, function, pipeline or install option exists. Native launching itself remains
the responsibility of a reviewed fixed adapter; this protocol does not invent one.

## Framing and artifacts

Each request/response starts with ASCII GEOCPU2 plus LF, then a big-endian uint32
JSON byte count and strict UTF-8 JSON. Request fields:
{protocol,tool,profile_id,nonce,spec_sha256,args,inputs}.
Input entries: {path,bytes,sha256,field,index}. Scalar index is null.
Only declared top-level path_fields are snapshotted beneath the fixed input root,
preserving relative paths. File-only inputs; directory/SAFE-tree manifests need an
explicit reviewed adapter contract. Snapshots are read-only and hash-checked before
and after execution; this is NOT an OS immutability guarantee.

Success fields: {protocol,tool,nonce,status:"ok",data,files,proof}.
Each file: {path,bytes,sha256,validator_id}; each following binary body has its own
big-endian uint64 length. Counts, aggregate bytes, paths, hashes, validator identity,
trailing bytes, data artifacts and canonical output_sha256 must all agree.
Failure fields: {protocol,tool,nonce,status:"error",error:{code,message,
retryable:false,exception_chain:[{type,message}]}} with a nonzero real process exit.
Original exception/cause strings survive in ScientificToolError.remote_error.

Content validators: strict UTF-8, closed bounded JSON, rectangular CSV, PNG
signature/chunks/CRC/bounded zlib stream, child rasterio GeoTIFF readability/CRS/affine,
child h5py closed HDF5 object tree. These are transport/content checks, NOT scientific
validation. Rasterio/h5py must be pinned in the actual child's requirements before
using those validators. No TIFF/HDF5 scientific acceptance is claimed here.

Parent receives into a private quarantine directory; only validated outputs are
exclusively created in the fixed output boundary. The original _outputs recalculates
hashes. Child installed_versions and output_sha256 are retained. New isolated tool
output schemas MUST permit the added provenance.isolation object, whose fields are:
profile_id,profile_sha256,worker_sha256,python_version,python_sha256,
build_receipt_sha256,installed_versions,spec_sha256,protocol,native_projects,
gpu_requested:false,runtime_install:false,os_sandbox:false,evidence_directory.
This optional schema addition is for isolated candidate tools, not a baseline rewrite.

## Resource and trust limits

Fixed shell=False child launch, -I -B; live bounded stdout/stderr; wall deadline;
Windows Job Object memory/tree termination and <=2 CPU affinity, or POSIX worker
address-space/CPU/file limits and process group termination. Unsupported Windows
resource binding rejects execution. Private HOME/cache/temp, <=2 thread variables,
GPU variables hidden, tracing disabled, PROJ network disabled. Environment flags,
process limits and source hashes are NOT an OS/network/filesystem sandbox. Reviewed
upstream code must be offline. Initial process setup precedes some resource binding;
untrusted arbitrary code is not supported. No guarantee of a malicious child sandbox.

Private job evidence and failures are retained for administrator retention handling.
The source-copy policy is explicit file manifests only, never recursive project copy.
No old native_cpu_bridge profile or behavior was changed.

## Local tests and handoff

run_local_contracts.py uses the already-present local Flow skill source, no install.
It runs tests/test_isolated_cpu_bridge_v2.py once with isolated CPU environment and
writes logs, local-test-report-r1.json and source-package-manifest.json. Reports are
exclusive-create and preserve failures. Protocol fixtures are clearly synthetic.
Actual decorator tests require real jsonschema and are skipped, not mocked, when
unavailable. Real GPR cross-interpreter acceptance is NOT RUN: its concrete reviewed
interpreter/profile/source closure is pending. Its legacy fixed CPU environment flag
is not yet propagated by this v2 profile. Peer GPR20/20 are NOT v2 passes.

Parent overlay must require collection_contracts.py's exact BEFORE hash from
baseline-precondition.json, then bind its actual AFTER hash and every explicit file
in source-package-manifest.json. The manifest excludes its own recursive self-hash.
Parent owns catalog staging and deployment. Missing dependencies, schema extensions,
native receipts or genuine runtime acceptance remain pending; do not call this
source package usable/accepted just because its files exist.
