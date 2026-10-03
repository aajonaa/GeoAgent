---
id: earthquake_energy
name: Earthquake energy estimation
description: Estimate energy from moment magnitude and compare earthquake energies. 地震震级能量估算与比较。
when_to_use: A task provides Mw and asks for estimated energy or energy ratios.
required_inputs: [Moment magnitude Mw]
tools: [GeoMagnitudeToEnergy, read_file, write_file, execute_python]
constraints:
  - The relation is empirical, not a measured energy or a scientific accuracy guarantee.
  - Mw is moment magnitude, not intensity or an arbitrary magnitude scale.
  - Preserve full computed values in files; round only for presentation.
expected_outputs: [Energy in joules, Formula and limitations, Requested files]
---
# Earthquake energy estimation

Confirm that the supplied magnitude is Mw. Use GeoMagnitudeToEnergy for the
estimate E = 10 ** (1.5 * Mw + 4.8) joules. The tool also returns metric tons of
TNT equivalent, using 4.184e9 J per ton. Neither quantity measures actual damage.

For comparisons, use successful tool results or an explicitly executed program.
Do not independently invent or retype rounded numbers into a report. Reuse the
same numeric values when writing a CSV and narrative. Inspect generated files
when needed. State the empirical nature of the estimate in the answer.

This procedure is guidance, not a mandatory fixed tool sequence. If the user
specifically asks for Python, execute the formula in Python rather than forcing
the domain tool. Do not repeat already successful identical calculations.
