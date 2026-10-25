---
id: github_geology_geostat_validation
name: "Geostatistical models and background validation"
description: "Compare classical, Cressie-Hawkins and Dowd empirical semivariograms on the same geological sample pairs. Estimate joint spatial/temporal geological semivariance from repeated fixed-station measurements, including both cross-time directions. Fit correlated variance and correlation length to a supplied measured exponential semivariogram with fixed known nugget. Regularize point covariance to two explicit finite discrete geological sampling supports. Measure leave-one-out interpolation errors for a supplied fixed spherical geological variogram, retaining every validation fold. Measure multivariate chemical departure from a caller-declared background in nonredundant ILR coordinates."
when_to_use: "Geostatistical models and background validation from explicit supplied geological measurements"
tools:
- GeoSKGstatRobustVariogram
- GeoSKGstatSpaceTimeVariogram
- GeoGSToolsVariogramFit
- GeoGSToolsBlockSupportCovariance
- GeoSKGstatKrigingLOO
- GeoGeochemBackgroundDistance
required_inputs:
- Explicit measured data, units, source and scientific assumptions
constraints:
- Use only the operation needed for the question
- Preserve missingness, units, source hashes and uncertainty
- Do not infer ore grade, reserves or mineral identity
- No installation, online fetch or arbitrary Python at call time
expected_outputs:
- Numeric scientific evidence and native provenance
---

# Geostatistical models and background validation

## When to use

Compare classical, Cressie-Hawkins and Dowd empirical semivariograms on the same geological sample pairs. Estimate joint spatial/temporal geological semivariance from repeated fixed-station measurements, including both cross-time directions. Fit correlated variance and correlation length to a supplied measured exponential semivariogram with fixed known nugget. Regularize point covariance to two explicit finite discrete geological sampling supports. Measure leave-one-out interpolation errors for a supplied fixed spherical geological variogram, retaining every validation fold. Measure multivariate chemical departure from a caller-declared background in nonredundant ILR coordinates.

## Required inputs

Use the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.

## Procedure

1. Select the operation matching the scientific question and read its limitations.
2. Obtain the declared measurements, units, reference compositions or model parameters.
3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.
4. Invoke the named native function with args as a dictionary or JSON object string.
5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.

## Tools and synthetic examples

### GeoSKGstatRobustVariogram

Compare classical, Cressie-Hawkins and Dowd empirical semivariograms on the same geological sample pairs.

Entrypoint: `geological_agent.geology.github_expansion_geology:robust_variogram_comparison`. Example: `assets/github-expansion-geology/GeoSKGstatRobustVariogram.json`. All examples are explicitly SYNTHETIC.

Projected metres only; no geodesic correction or directional search. Stationarity and representative sampling remain scientific assumptions. Empty bins remain null with zero counts.

Upstream source: [pinned implementation](https://github.com/mmaelicke/scikit-gstat/blob/813a4c4f5173df100e64cc84c8ad56d928c9e0af/skgstat/estimators.py).

### GeoSKGstatSpaceTimeVariogram

Estimate joint spatial/temporal geological semivariance from repeated fixed-station measurements, including both cross-time directions.

Entrypoint: `geological_agent.geology.github_expansion_geology:space_time_variogram`. Example: `assets/github-expansion-geology/GeoSKGstatSpaceTimeVariogram.json`. All examples are explicitly SYNTHETIC.

Equal time spacing, complete data and fixed stations required. Excludes zero-space and zero-time pairs. Upstream marginal fits occur during construction but are not used as scientific outputs. Both time orderings are evaluated because the release's single ordering is asymmetric.

Upstream source: [pinned implementation](https://github.com/mmaelicke/scikit-gstat/blob/813a4c4f5173df100e64cc84c8ad56d928c9e0af/skgstat/SpaceTimeVariogram.py).

### GeoGSToolsVariogramFit

Fit correlated variance and correlation length to a supplied measured exponential semivariogram with fixed known nugget.

Entrypoint: `geological_agent.geology.github_expansion_geology:exponential_variogram_fit`. Example: `assets/github-expansion-geology/GeoGSToolsVariogramFit.json`. All examples are explicitly SYNTHETIC.

One isotropic exponential family, fixed nugget and unweighted least squares. Parameter covariance must be finite; goodness of fit is not evidence of stationarity or prediction accuracy.

Upstream source: [pinned implementation](https://github.com/GeoStat-Framework/GSTools/blob/1edd2b93bf429803d716a9cbab125362583575de/src/gstools/covmodel/fit.py).

### GeoGSToolsBlockSupportCovariance

Regularize point covariance to two explicit finite discrete geological sampling supports.

Entrypoint: `geological_agent.geology.github_expansion_geology:block_support_covariance`. Example: `assets/github-expansion-geology/GeoGSToolsBlockSupportCovariance.json`. All examples are explicitly SYNTHETIC.

Exact for the supplied equally weighted discrete nodes, only an approximation to a continuous block. Isotropic stationary exponential covariance and zero nugget are explicit; no inferred grade.

Upstream source: [pinned implementation](https://github.com/GeoStat-Framework/GSTools/blob/1edd2b93bf429803d716a9cbab125362583575de/src/gstools/covmodel/models.py).

### GeoSKGstatKrigingLOO

Measure leave-one-out interpolation errors for a supplied fixed spherical geological variogram, retaining every validation fold.

Entrypoint: `geological_agent.geology.github_expansion_geology:kriging_leave_one_out`. Example: `assets/github-expansion-geology/GeoSKGstatKrigingLOO.json`. All examples are explicitly SYNTHETIC.

The model must be fixed independently of validation data. All samples must fit within its range, no duplicate locations, at most 32 observations, and any failed fold fails the whole call.

Upstream source: [pinned implementation](https://github.com/mmaelicke/scikit-gstat/blob/813a4c4f5173df100e64cc84c8ad56d928c9e0af/skgstat/Kriging.py).

### GeoGeochemBackgroundDistance

Measure multivariate chemical departure from a caller-declared background in nonredundant ILR coordinates.

Entrypoint: `geological_agent.geology.github_expansion_geology:geochemical_background_distance`. Example: `assets/github-expansion-geology/GeoGeochemBackgroundDistance.json`. All examples are explicitly SYNTHETIC.

Empirical covariance is not robust to background contamination. Background selection is the caller's scientific responsibility; no automatic anomaly probability, ore label, cutoff or grade. Rejects singular/ill-conditioned backgrounds.

Upstream source: [pinned implementation](https://github.com/scikit-learn/scikit-learn/blob/25dee604bae18205b01548348388baf7a1cdfe0e/sklearn/covariance/_empirical_covariance.py).

## Interpretation and constraints

These calls use named upstream scientific kernels. A numerical result does not authenticate input data or establish geological representativeness. No tool infers ore grade, reserves or mineral presence. Synthetic examples are numerical oracles only. Units and structural/depth conventions are part of the measurement model.

## Native errors

ScientificToolError exposes code, message and retryable. Correct invalid arguments or unsupported assumptions before retrying. missing_dependency and incompatible_dependency require the parent-controlled private worker; the tool never changes the environment. A failed scientific kernel returns an error, never a local substitute formula or placeholder value.

## Source interface and delivery

Kind: github_expansion_geology. Module: geological_agent.geology.github_expansion_geology. Functions accept args=dict or args=JSON-object-string through collection_contracts.operation. No operation in this Skill requires output_dir or writes artifacts; the LAS reader alone reads one declared local file. Native provenance records pinned dependencies, source commit, input hash, implementation hash, contract hash, and empty artifact hashes.

## Acceptance evidence

Positive independent analytic oracles, per-operation negative constraints and provenance assertions are authored in `tests_local/test_github_expansion_geology.py` and `catalog/source_delivery/github-expansion-20261025/groups/geology/oracle-cases.json`. They have NOT BEEN RUN. This r2 source has NOT BEEN TESTED. Parent reports a separate successful SQLAlchemy 1.4.54 / APSG 2.0.6 / ObsPy 1.4.2 joint import; that is not scientific acceptance of these operations.

## Current availability

Source authored and generated metadata only. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Unit, workflow, model-workflow and platform validation: not_run. Receiving-lab approval and adapter license: pending. Bingham axial confidence and CIPW normative mineralogy are blocked and excluded from all five active Skills; see the group blocked-operations.json. Parent owns fixed module whitelist, worker dispatch, registry integration and CPU acceptance. Existing online229 is unchanged.
