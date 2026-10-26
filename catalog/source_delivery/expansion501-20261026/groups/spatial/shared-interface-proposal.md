# Minimal shared integration proposal, not implemented here

Status: source-only, not deployed, not submitted, model workflow not_run.

## Why the accepted bridge is insufficient

`collection_contracts.operation` invokes `_dependencies(spec)` in the main
interpreter before the adapter. A private venv cannot satisfy that check.
`native_cpu_bridge.invoke` rejects `output_dir`, any artifact list and any
nonempty output hash map. It implements JSON-only v1, not raster/cloud transport.
Its captured output is bounded after process completion, rather than while read.
Do not alter accepted profiles or route these kernels through that interface.

## Smallest parent-owned extension

1. Add a catalog-only `source_interface.isolated_profile` binding. Resolve it
   against a fixed, separately reviewed operation-to-profile allowlist. It is
   never an input-schema property, environment override, executable argument,
   arbitrary upstream name or caller-selected pipeline.
2. In `operation`, retain main argument/schema/finite/size checks and canonical
   input content hashing. Branch before the current `_dependencies(spec)` call
   only for that trusted binding. All other operations retain the current path.
3. The fixed child entry runs the existing exact `_dependencies(spec)` in its
   interpreter, using unchanged truthful upstream requirements. A parent-owned
   local-execution helper avoids recursive IPC without an environment-based
   bypass. The child validates input again and invokes a fixed named function.
4. Bind interpreter, entry source, support source, native executable and complete
   native library/plugin closure hashes plus reviewed build/license receipts.
   PDAL native 2.9.1 is NOT the Python pdal distribution version. GRASS and CBC
   likewise use native receipts, never invented Python requirements.
5. Return a bounded JSON envelope containing tool ID, real exit status, typed
   result, actual interpreter/package identities and artifact descriptors:
   `{name, bytes, sha256, media_type}`. No absolute child paths. Reject duplicate
   keys, nonfinite JSON, unknown fields, mismatched operation/profile/identity.
6. Drain stdout/stderr with limits while the child runs; enforce wall/CPU/RAM/
   file-count/aggregate-byte limits. Kill the entire worker process group on a
   limit. Private HOME/cache/temp, no GPU visibility, <=2 threads, no installer,
   no network/model credentials. A private venv is not a network sandbox.
7. Copy only declared regular files from the private output root into the new
   main result directory; reject absolute/traversal names, symlinks and hard
   links, enforce content-format checks, size and digest before and after copy.
   Recheck source identity around execution. Do not expose a child path as a
   usable main-runtime artifact.
8. The main decorator validates the full typed result and runs its existing
   `_outputs` to generate final artifact hashes. `installed_versions` must come
   from the verified child receipt, not the main interpreter. Preserve both
   boundary/input hashes and the exact worker source/native identity in a
   parent-agreed provenance schema. Do not forge or drop existing fields.

## Spatial handoff boundary

The new support code implements private scientific kernels and an internal
fixed native launcher, NOT this shared IPC. Eleven named adapter definitions
remain absent from catalog-additions.json. Their closed candidate schemas live
in pending-contracts.json. All 19 assignment rows remain blocked; no main-runtime
integration or receiving-lab certification is claimed.

`native-profile.json` is deliberately absent. The internal launcher needs a
trusted `projects` map for PDAL/GRASS/CBC with `version`, `root`, relative
`executable`, relative `build_receipt`, `closure_complete:true`, and
`files_sha256` covering the executable/receipt/native closure. The receipt must
identify project/version and `license_review_complete:true`. These are operator
reviewed identities, never request parameters. No native binary hash was
invented. Parent must reconcile this internal receipt with its shared profile
before execution; do not create an independent production dispatch mechanism.

## Primary evidence and remaining qualifications

- PuLP 3.3.0 `coin_api.py::get_status` can report LpStatusOptimal with
  LpSolutionIntegerFeasible after stopping. Both statuses must prove optimality:
  https://github.com/coin-or/pulp/blob/3.3.0/pulp/apis/coin_api.py
- Landlab 2.11.0 BedrockLandslider returns suspended yield divided by dt despite
  its volume wording. The pending adapter labels the rate and multiplies by dt
  for solid-volume accounting; its alternative upstream D8/MFD routing requires
  independent equivalence/domain acceptance, not an equivalence claim:
  https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/bedrock_landslider/bedrock_landslider.py
- TidalFlowCalculator has no dt argument. Its inundation formula uses elevation
  relative to MSL. Both depth and inundation receive explicitly translated
  relative elevations with upstream mean_sea_level=0:
  https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/tidal_flow/tidal_flow_calculator.py
- The parcel adapter retains actual DataRecord time columns, returned links,
  volumes, diameters, exports and abrasion loss. Routing is explicitly fixed to
  the initial downhill tree; it does not claim dynamic river-network rerouting.

Native license closure/build identities and two auxiliary full source SHAs
(PuLP/CBC) remain unresolved. Existing old pins are unchanged; PuLP==3.3.0 is
only a NEW pending private profile pin. No main environment replacement.
