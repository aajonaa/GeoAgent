# Pending seismic inversions, r6

Two actual named adapters have been authored; neither is registered, certified,
deployed, submitted, or counted as accepted. The existing 42-entry contribution
catalog and old failures are unchanged. Parent-owned v2 is the only integration
route; there is no new user-selectable shell, executable or callable.

## Resolved by primary evidence
- PyLops 2.6.0 has Marchenko.apply_onepoint and forwards public LSQR options.
  Its returned arrays omit solver metadata. show=True exposes the actual pinned
  SciPy summary; the adapter checks both coupled residuals and stationarity using
  upstream operators without replacing the solver.
- pyGIMLi 1.6.0 release commit is d598724a75cf0abbefcb354b8cd71bb48c232fc6.
  startModel is slowness; mapped return is velocity. A public post-step observer
  exposes data/total objectives without changing optimizer state or termination.
- Official pygimli/pgcore wheels were hash-checked and inspected using a local
  three-stage Flow. This proves static identity only, not ABI compatibility.

## Remaining concrete gates
- Parent v2 main-runtime dispatch, real private dependency checks and exact typed
  provenance agreement. Inputs and outputs contain no file artifacts.
- Actual independent Marchenko nonzero two-lag rational-reference execution.
- Actual heterogeneous crosshole observation-reference execution; no posterior
  model-identifiability claim. ClassicInversion catches some internal step errors
  and offers no structured success code; the adapter says not_certified.
- pgcore native source/build correspondence, runtime ABI and bundled library
  license closure. Package-level Apache metadata does not license every bundled
  SuiteSparse/BLAS/Boost/GCC library.
- Existing Bouguer/Edge/Tesseroid/Eigenfunction issues and 13 historical numeric
  oracle gaps were not repaired in this bounded two-operation pass.

## Known newly authored issue, not silently repaired
The superseded group v1 diagnostic worker maps JSON decoding ValueError to
upstream_failure instead of invalid_arguments. A retained negative test exposes
it. Parent v2 replaces that route; do not register or deploy the group v1 worker.
Minimal repair, if that diagnostic source is ever reused, is explicit decoding
exception translation. No such repair was performed.

## Status and source stability
The scientific source pass is complete but unverified. See fixed-profile-
requirements-r6.json for exact pins/bounds and pending-tool-contracts-r6.json for
closed schemas. The group v1 worker is superseded diagnostic source, not an
integration alternative. Local stdlib protocol/reference checks are separate
from the four opt-in scientific direct calls, which have not run here.
No remote setup/upload retry, installation, production change, GPU, Git or push.

