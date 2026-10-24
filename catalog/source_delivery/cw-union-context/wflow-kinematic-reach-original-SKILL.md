---
id: wflow_kinematic_reach
name: Original Wflow single-reach routing
description: A bounded archived-original SI kinematic-wave reach step.
when_to_use: Supplied SI parameters for one river reach and timestep.
tools:
  - EarthWflowKinematicWaveReachStep
---

Confirm all supplied inflows, previous flow, alpha/beta, reach length and timestep with their SI units. Do not infer missing parameters. Call the single native operation, check its returned continuity residual and tolerance, and preserve its source provenance. A dry reach with positive lateral inflow and beta<1 is unsupported and must not be silently repaired. This is an archived original kernel, not full Wflow/PCRaster, a catchment calibration or Wflow.jl. No web, model or code execution is needed.
