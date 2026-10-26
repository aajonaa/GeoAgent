---
id: expansion501-geophysics-pending-imaging
name: Pending audited seismic imaging inversions
status: source_revised_unverified
formal_eligible: false
---

# Availability and delivery
Source-authored only. Both operations remain blocked and absent from the active
contribution catalog. not_deployed; not_submitted; model workflow: not_run.
This handoff is not an AI Lab certification or a usable main-runtime registration.

# Scientific scope
GeoSeismicMarchenkoRedatuming uses the actual pinned PyLops coupled inverse solver.
GeoSeismicTraveltimeTomography uses actual pyGIMLi regularized Dijkstra tomography.
They are distinct from forward traveltime and single-scattering migration tools.

# Inputs and units
Marchenko requires square collocated acquisition, calibrated doubled upstream
response density, independently supplied direct waves, time in seconds and
spacing in metres. Do not infer an amplitude normalization from field data.
Tomography requires fixed crosshole mesh/sensor coordinates in metres, measured
traveltimes and strictly positive measurement errors in seconds, physical
velocity bounds in m/s, and explicit regularization.

# Model workflow
not_run. Load the pending closed schema and synthetic example before planning.
Use only parent-owned isolated_cpu_bridge_v2.py / worker_v2.py once integrated.
Never install dependencies, select executables, fetch data, or use a GPU at call time.
Do not treat a successful private direct call as proof of main-runtime dispatch.

# Outputs and interpretation
Bounded typed JSON with explicit units, artifacts=[] and contract provenance.
Marchenko reports real LSQR stop/iteration data and separate coupled residuals.
Tomography reports observed iteration conditions without fabricating a success
code. Regularized velocity is nonunique; posterior uncertainty is not estimated.

# Negative constraints
Reject missing errors, nonfinite data, shape/axis mismatches, invalid velocity
bounds, impossible fast arrivals and acquisition/grid limits. Do not relax
numeric tolerances to obtain a pass.

# Evidence and handoff
See the group pending-tool-contracts-r6.json, fixed-profile-requirements-r6.json,
sources-pending-two-r6.json and acceptance/pending-two-r6/ files.
Native ABI/build/source/license closure, actual scientific references and parent
v2 end-to-end registration remain pending. Historical r1 failures are unchanged.

