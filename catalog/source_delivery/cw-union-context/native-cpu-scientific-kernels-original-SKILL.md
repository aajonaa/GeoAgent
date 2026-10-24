---
id: native_cpu_scientific_kernels
name: Original native CPU scientific kernels
description: Genuine VIC rain/snow partition, Madagascar seismic FFT, and HPGL directional semivariogram with explicit units and original compiled kernels.
when_to_use: Select only the required operation for precipitation phase, seismic trace spectrum or projected geochemical sample variability; do not invoke all three merely because they share a skill.
tools: [HydroVICPrecipitationPhase, SeismicMadagascarFFT, GeoHPGLDirectionalSemivariogram]
required_inputs: [Caller-supplied measurements or clearly labelled synthetic test inputs, Explicit physical units and sampling or geometric conventions]
constraints: [CPU only and offline, No runtime install or compilation, No arbitrary code or executable/library path arguments, No claims of full VIC or Madagascar or HPGL engine coverage, HPGL redistribution license review remains pending]
expected_outputs: [Observed numeric values with units, Original source and compiled binary and input hashes, Method scope and scientific limitations]
---

# Original Native CPU Scientific Kernels

## Choose the scientific operation

Use HydroVICPrecipitationPhase for liquid/frozen precipitation partition from
air temperature and precipitation depth per supplied time step. Supply equal
arrays in degrees Celsius and millimetres. Retain caller-specified transition
thresholds; defaults are +1 and -1 degrees Celsius. The upper threshold must
exceed the lower threshold. This is the original VIC phase kernel, not a
catchment model or a snowpack forecast. Rain plus snow preserves supplied depth.

Use SeismicMadagascarFFT for a real, uniformly sampled seismic trace. Supply
the actual sampling interval in seconds and the amplitude unit. The original
Madagascar archived Kiss FFT uses float32. The returned forward DFT is unscaled;
the two-sided amplitude is abs(DFT)/N. There is no hidden window, padding,
detrending, resampling or conversion to a one-sided amplitude. Frequencies are
the full signed axis, including a negative Nyquist bin for even sample counts.

Use GeoHPGLDirectionalSemivariogram for experimental directional sample
variability, not spatial prediction or reserve estimation. Coordinates must
already be projected metres with a documented vertical convention. Select a
positive x/y/z search direction and scientifically justified lag spacing,
width, first lag and transverse bandwidth. The original HPGL C++ search uses
inclusive lower and exclusive upper lag edges. Empty bins return zero, just
as equal-valued pairs do; never interpret zero as evidence of pair support.
Do not silently relabel longitude/latitude as projected metres.

## Interface and execution evidence

The reviewed JSON schemas are authoritative. Tools accept dictionaries, JSON
object strings or args=. The runtime exposes only fixed function names and a
reviewed CPU dependency profile. Do not ask users for commands, code, library
paths or dependency installation instructions. No GPU, network, installation
or compilation occurs during a scientific call. Missing prepared dependencies
are deployment prerequisites, not permissions to substitute another algorithm.

Read actual tool observations and preserve units, input identity, original
source hashes and compiled-binary/build-receipt provenance. Independent calls
may be batched when the task genuinely requires them. Do not rerun successful
scientific work simply to change answer formatting. These operations return
JSON, not image or file artifacts.

## Limits and acceptance

Never fabricate input observations, claim a complete upstream simulation,
or turn semivariance or a spectrum into a mineral occurrence/grade/reserve
claim. Synthetic acceptance fixtures are not field data. Independent CPU
interface and numerical tests do not establish an agent-workflow evaluation
or receiving-lab approval. HPGL's README and license wording require separate
review before redistribution. No formal AI Lab delivery package is issued.

