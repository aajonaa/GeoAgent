"""Disjoint candidate interfaces. No edits to the parent's registry/catalog."""


def number(low, high, **extra):
    return {"type": "number", "minimum": low, "maximum": high, **extra}


def array(low, high, count=4096):
    return {"type": "array", "minItems": 1, "maxItems": count,
            "items": number(low, high)}


VIC = "HydroVICPrecipitationPhase"
FFT = "SeismicMadagascarFFT"
HPGL = "GeoHPGLDirectionalSemivariogram"
SPECS = {
    VIC: {
        "name": VIC, "project_id": 39, "project": "VIC",
        "description": "Partition precipitation into liquid rain and snow using the original VIC air-temperature phase kernel. Not a full VIC simulation.",
        "entrypoint": "adapters.HydroVICPrecipitationPhase",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["air_temperature_c", "precipitation_mm"],
            "properties": {
                "air_temperature_c": array(-100, 100),
                "precipitation_mm": array(0, 100000),
                "max_snow_temperature_c": number(-100, 100, default=1.0),
                "min_rain_temperature_c": number(-100, 100, default=-1.0),
            },
        },
        "constraints": ["Arrays must have equal lengths.", "max_snow_temperature_c > min_rain_temperature_c.", "Precipitation is a depth per supplied time step; no rate or temperature conversion."],
        "example_arguments": {"air_temperature_c": [-2, -1, 0, 1, 2], "precipitation_mm": [10, 10, 10, 10, 10]},
        "output_fields": {"rain_mm": "array[number]", "snow_mm": "array[number]", "sample_count": "integer"},
        "units": {"rain_mm": "mm/time_step", "snow_mm": "mm/time_step", "air_temperature_c": "degree_Celsius"},
        "library": "libvic_phase.so", "symbol": "geo_vic_partition",
        "precision": "upstream double", "license": "MIT",
    },
    FFT: {
        "name": FFT, "project_id": 131, "project": "Madagascar",
        "description": "Analyze a real seismic trace with the unchanged archived Madagascar Kiss FFT C kernel. Full unscaled forward DFT, no padding/window/detrending. Not the whole Madagascar suite.",
        "entrypoint": "adapters.SeismicMadagascarFFT",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["samples", "sampling_interval_s"],
            "properties": {
                "samples": {**array(-1e12, 1e12), "minItems": 2},
                "sampling_interval_s": {"type": "number", "exclusiveMinimum": 1e-9, "maximum": 86400},
                "amplitude_unit": {"type": "string", "enum": ["arbitrary", "m", "m/s", "Pa"], "default": "arbitrary"},
            },
        },
        "constraints": ["2 to 4096 finite real samples.", "Original float32 arithmetic is retained; conversion to JSON numbers does not create double-precision results.", "Full signed frequency axis; the even-N Nyquist bin is negative."],
        "example_arguments": {"samples": [1, 0, 0, 0, 0, 0, 0, 0], "sampling_interval_s": 0.01, "amplitude_unit": "m/s"},
        "output_fields": {"frequency_hz": "array[number]", "real": "array[number]", "imaginary": "array[number]", "amplitude_two_sided": "array[number]", "sample_count": "integer", "normalization": "string"},
        "units": {"frequency_hz": "Hz", "real": "amplitude_unit", "imaginary": "amplitude_unit", "amplitude_two_sided": "amplitude_unit"},
        "library": "libmadagascar_fft.so", "symbol": "geo_madagascar_fft",
        "precision": "upstream default float32",
        "license": "BSD-3-Clause notices in selected Kiss FFT sources; upstream project COPYING.txt also retained",
    },
    HPGL: {
        "name": HPGL, "project_id": 86, "project": "HPGL",
        "description": "Calculate a directional experimental semivariogram from projected 3D samples with original HPGL C++ point-set code. Axis-aligned positive-direction cylinder; not kriging or full HPGL.",
        "entrypoint": "adapters.GeoHPGLDirectionalSemivariogram",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["x_m", "y_m", "z_m", "values", "lag_separation_m", "lag_width_m", "first_lag_m", "lag_count", "bandwidth_m"],
            "properties": {
                "x_m": {**array(-1e7, 1e7, 512), "minItems": 2},
                "y_m": {**array(-1e7, 1e7, 512), "minItems": 2},
                "z_m": {**array(-1e7, 1e7, 512), "minItems": 2},
                "values": {**array(-1e12, 1e12, 512), "minItems": 2},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "x"},
                "lag_separation_m": number(1e-6, 1e7),
                "lag_width_m": number(1e-6, 1e7),
                "first_lag_m": number(1e-6, 1e7),
                "lag_count": {"type": "integer", "minimum": 1, "maximum": 64},
                "bandwidth_m": number(1e-6, 1e7),
                "value_unit": {"type": "string", "enum": ["arbitrary", "g/t", "ppm", "m"], "default": "arbitrary"},
            },
        },
        "constraints": ["Coordinates must already be projected metres, not longitude/latitude. No automatic CRS conversion.", "All four input arrays must have equal lengths.", "lag_width_m <= lag_separation_m and first_lag_m > lag_width_m/2.", "Upstream float32 samples/output retained.", "Upstream returns zero both for empty bins and equal-valued sample pairs; zero is not proof that a bin contains observations."],
        "example_arguments": {"x_m": [0, 1, 2, 3], "y_m": [0, 0, 0, 0], "z_m": [0, 0, 0, 0], "values": [0, 1, 2, 3], "lag_separation_m": 1, "lag_width_m": 0.5, "first_lag_m": 1, "lag_count": 3, "bandwidth_m": 0.1, "value_unit": "g/t"},
        "output_fields": {"lag_center_m": "array[number]", "semivariance": "array[number]", "sample_count": "integer", "empty_bin_policy": "string"},
        "units": {"lag_center_m": "m", "semivariance": "value_unit squared"},
        "library": "libhpgl_variogram.so", "symbol": "geo_hpgl_variogram",
        "precision": "upstream float32 samples/output, double accumulation",
        "license": "HPGL license.txt BSD terms; README separately limits use wording: distribution review required",
        "distribution_license_review_required": True,
    },
}

for spec in SPECS.values():
    spec.update({
        "generates_artifacts": False, "source_mode": "original_native_kernel",
        "runtime_install": False, "runtime_compile": False,
        "network_required": False, "gpu_required": False,
        "errors": {"invalid_arguments": "Invalid schema, nonfinite values or domain constraints.", "missing_dependency": "Prepared fixed native library is absent.", "integrity_error": "Source, bridge or prepared binary no longer matches the build receipt.", "execution_error": "Native allocation or execution failed."},
        "output_schema": {
            "type": "object", "required": list(spec["output_fields"]) + ["units", "provenance"],
            "properties": {**{key: {"type": "array", "items": {"type": "number"}} if value == "array[number]" else {"type": value} for key, value in spec["output_fields"].items()}, "units": {"type": "object"}, "provenance": {"type": "object"}},
        },
    })

