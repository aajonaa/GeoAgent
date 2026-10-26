"""Materialize NEW geophysics delivery files using only the standard library.

This is an authoring generator, not a scientific/test/validation runner. It
does not import adapters, inspect the registry, install, access networks or
modify historical materials. Exclusive creation preserves existing files.
"""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
GROUP = "catalog/source_delivery/expansion501-20261026/groups/geophysics"
MODULE_PATH = "geological_agent/geology/expansion501_geophysics.py"
MODULE = "geological_agent.geology.expansion501_geophysics"
ASSET = "assets/expansion501-geophysics"
STATUS = "source_revised_unverified"
SYNTHETIC = "SYNTHETIC authoring fixture, not observations or an executed acceptance case"
BASE = ["numpy==2.1.3", "scipy==1.15.3", "jsonschema==4.25.1"]
SOURCES = {
    "obspy": dict(version="1.4.2", repository="obspy/obspy", commit="a629e8c021052904b6b8d62699d03f2a3721ae63", license="LGPL-3.0", license_file="LICENSE.txt", requirements=BASE + ["matplotlib==3.10.7", "SQLAlchemy==1.4.54", "setuptools==80.9.0"]),
    "bruges": dict(version="0.5.4", repository="agilescientific/bruges", commit="24e2e7912f49089465dd622363fd2788029266b1", license="Apache-2.0", license_file="LICENSE.txt", requirements=BASE),
    "harmonica": dict(version="0.7.0", repository="fatiando/harmonica", commit="b9f9c00b0999f470dcae971b19add28b055633c9", license="BSD-3-Clause", license_file="LICENSE.txt", requirements=BASE + ["pandas==2.3.0", "numba==0.68.0", "xarray==2026.9.0", "scikit-learn==1.7.2", "choclo==0.3.2", "verde==1.8.1", "xrft==1.0.1"]),
    "empymod": dict(version="2.6.0", repository="emsig/empymod", commit="7a7c221da5940a8e0d8f60478b929e2690806521", license="Apache-2.0", license_file="LICENSE", requirements=BASE + ["numba==0.68.0", "libdlf==0.3.0", "scooby==0.10.2"]),
    "geoana": dict(version="0.9.0", repository="simpeg/geoana", commit="7c47ec2e1253e698c26c95d6dd0c7e493a1c8630", license="MIT", license_file="LICENSE", requirements=BASE),
    "boule": dict(version="0.6.0", repository="fatiando/boule", commit="8666d0823c667c543bfce503cc3759b9c3047287", license="BSD-3-Clause", license_file="LICENSE.txt", requirements=BASE),
    "disba": dict(version="0.7.0", repository="keurfonluu/disba", commit="18b7d023288f2bf22d2f128e8ca6a10d15b5913a", license="BSD-3-Clause", license_file="LICENSE", requirements=BASE + ["numba==0.68.0", "matplotlib==3.10.7"]),
    "simpeg": dict(version="0.25.2", repository="simpeg/simpeg", commit="5f2d643c484ebe8b8ccfa029aa7377d133f2f53f", license="MIT", license_file="LICENSE", requirements=BASE + ["discretize==0.12.0", "pymatsolver==0.4.0", "geoana==0.9.0", "libdlf==0.3.0", "matplotlib==3.10.7", "typing-extensions==4.16.0"]),
    "pylops": dict(version="2.6.0", repository="PyLops/pylops", commit="97992be198c66a489c945c3feff31f6ed7d9117b", license="LGPL-3.0", license_file="LICENSE.md", requirements=BASE),
}
BLOCKED = {
    "GeoSeismicMarchenkoRedatuming": "PyLops 2.6.0 Marchenko.apply_onepoint discards LSQR termination/iteration diagnostics and does not expose the coupled residual operator. A reviewed coupled-residual/termination adapter is not authored; a finite returned focusing function alone cannot satisfy this inversion convergence contract. No upstream solver monkeypatch or falsely converged wrapper is registered.",
    "GeoSeismicTraveltimeTomography": "The TravelTimeManager.invert API is confirmed, but a fixed pyGIMLi/pgcore compiled build identity, matching release commit/license record and approved private CPU worker binding have not been established. No arbitrary executable/environment bridge or in-process unpinned native fallback is registered.",
}
FILES = [MODULE_PATH, GROUP + "/build_contribution.py"]
ROWS = []


def obj(properties, required=None):
    return dict(type="object", properties=properties, required=list(properties) if required is None else required, additionalProperties=False)


def number(description="Finite scientific value in its named unit.", low=-1e20, high=1e20):
    return dict(type="number", description=description, minimum=low, maximum=high)


def positive(description, low=1e-12, high=1e20):
    return number(description, low, high)


def integer(description, low, high):
    return dict(type="integer", description=description, minimum=low, maximum=high)


def string(description="Declared context, not independently authenticated provenance."):
    return dict(type="string", description=description, minLength=1, maxLength=2048)


def enum(values, description):
    return dict(type="string", enum=values, description=description)


def array(item=None, low=1, high=256, description="Ordered values in the documented unit and dimension."):
    return dict(type="array", items=item if item is not None else number(), minItems=low, maxItems=high, description=description)


def matrix(columns=3, rows=256, item=None, minrows=1):
    return array(array(item, columns, columns), minrows, rows)


def tensor(n1=32, n2=32, n3=512, item=None, min1=1, min2=1, min3=1):
    return array(array(array(item, min3, n3), min2, n2), min1, n1)


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def quantity(unit, *shape, item=None):
    schema = number("Output in " + unit, -1e200, 1e200) if item is None else item
    for dimension in reversed(shape):
        schema = array(schema, 0 if dimension is None else dimension, 8192 if dimension is None else dimension)
    return dict(unit=unit, schema=schema)


def add(tool_id, function, package, callable_name, task, fields, outputs, example, group, source_file, distinct, oracle, negatives, limits):
    ROWS.append(dict(id=tool_id, function=function, package=package, upstream_callable=callable_name,
        scientific_task=task, input_schema=obj({"input_source": string(), **fields}), outputs=outputs,
        example={"input_source": SYNTHETIC, **example}, skill_group=group, source_file=source_file,
        distinct_from_existing=distinct, numeric_oracle=oracle, negative_constraints=negatives, limitations=limits))


def wave(n=128, cycles=4, scale=1.):
    return [scale * math.sin(2 * math.pi * cycles * i / n) for i in range(n)]


def records():
    coord = number("Local Cartesian coordinate in m; no CRS transform.", -1e7, 1e7)
    dt = positive("Uniform sample interval in seconds.", .0001, 1)
    series = array(number("Finite calibrated or explicitly normalized amplitude.", -1e12, 1e12), 32, 4096)
    points = matrix(3, 128, coord)
    field_unit = enum(["mGal", "nT"], "One consistent potential-field unit for data and derivative numerators.")
    paz_fields = {
        "counts": array(number("Digitizer counts.", -1e12, 1e12), 256, 16384), "dt_s": dt,
        "record_start_s": number("Unix UTC seconds of the first sample.", -2208988800, 4102444800),
        "epoch_start_s": number("Inclusive UTC response-epoch start in Unix seconds.", -2208988800, 4102444800),
        "epoch_end_s": number("Inclusive UTC response-epoch end in Unix seconds.", -2208988800, 4102444800),
        "poles_rad_s": matrix(2, 32, number("Real/imaginary pole parts in rad/s."), 0),
        "zeros_rad_s": matrix(2, 32, number("Real/imaginary zero parts in rad/s."), 0),
        "normalization_factor": positive("PZ normalization constant, not instrument sensitivity.", 1e-30, 1e30),
        "sensitivity_counts_per_m_s": positive("Velocity response sensitivity in counts/(m/s).", 1e-20, 1e30),
    }
    paz = dict(counts=wave(512, 16, 2), dt_s=.01, record_start_s=0, epoch_start_s=-1, epoch_end_s=100,
               poles_rad_s=[], zeros_rad_s=[], normalization_factor=1, sensitivity_counts_per_m_s=2)
    add("GeoSeismicInstrumentDeconvolution", "seismic_instrument_deconvolution", "obspy", "obspy.core.trace.Trace.remove_response",
        "Recover calibrated velocity from counts using a supplied single-stage, stable PZ response covering the entire record epoch.",
        {**paz_fields, "reference_frequency_hz": positive("Response gain/normalization reference frequency Hz.", .001, 10000),
         "prefilter_hz": array(positive("Increasing cosine prefilter corner Hz.", .0001, 10000), 4, 4),
         "water_level_db": number("Spectral water level in dB.", 0, 120)},
        {"velocity_m_s": dict(unit="m/s", schema=array(number("Output in m/s", -1e200, 1e200), 0, 16384)), "dt_s": quantity("s")},
        {**paz, "reference_frequency_hz": 1, "prefilter_hz": [.1, .2, 20, 30], "water_level_db": 60},
        "waveform-quality", "obspy/core/trace.py", "Existing bandpass filters do not undo instrument gain/phase or supply physical motion units.",
        "Independent flat velocity sensor gain=2 counts/(m/s): a unit in-band velocity sinusoid produces 2-count amplitude and recovers 1 m/s away from the declared taper. Reference normalization is checked separately.",
        ["Epoch not covering the last sample", "Unpaired/unstable poles", "Prefilter crossing Nyquist", "Inconsistent PZ reference normalization"],
        ["Single-stage PZ only, not arbitrary StationXML or multistage decimation response.", "Mean removal, 5% taper, prefilter and water level are explicit; caller calibration is not authenticated."])
    add("GeoEMLayeredBipoleResponse", "em_layered_bipole_response", "empymod", "empymod.model.bipole",
        "Calculate a frequency-domain finite electric-bipole response in a supplied horizontally layered VTI electrical model.",
        {"interfaces_depth_m": array(coord, 1, 16), "horizontal_resistivity_ohm_m": array(positive("Horizontal resistivity ohm*m.", .001, 1e12), 2, 17),
         "anisotropy_sqrt_rhov_rhoh": array(positive("sqrt(vertical/horizontal resistivity), dimensionless.", .1, 10), 2, 17),
         "source_endpoints_end_m": matrix(3, 2, coord, 2), "receivers_end_azimuth_dip": matrix(5, 16, number("East,north,depth m; azimuth and dip degrees.", -1e7, 1e7)),
         "frequency_hz": array(positive("Frequency Hz.", .001, 1e5), 1, 32), "current_a": positive("Source current A.", 1e-6, 1e5)},
        {"electric_real_v_m": quantity("V/m", None, None), "electric_imag_v_m": quantity("V/m", None, None)},
        dict(interfaces_depth_m=[0, 100], horizontal_resistivity_ohm_m=[1e12, 100, 10], anisotropy_sqrt_rhov_rhoh=[1, 1, 1],
             source_endpoints_end_m=[[0, 0, 10], [10, 0, 10]], receivers_end_azimuth_dip=[[100, 0, 10, 0, 0]], frequency_hz=[1, 10], current_a=1),
        "electromagnetic", "empymod/model.py", "Existing magnetic dipoles/prisms are static magnetization sources, not controlled-source EM in conductive VTI layers.",
        "Independent low-frequency homogeneous whole-space finite-electrode reference: rho=100 ohm*m,I=1 A, endpoints x=0,10m, receiver x=100m gives Ex=rho/(4*pi)*(1/100^2-1/90^2) V/m; compare magnitude 0.000186664857 to the converged low-frequency limit, then require an independent heterogeneous layered benchmark.",
        ["Source crosses a layer interface", "Receiver on source", "Nonpositive resistivity/anisotropy", "Unordered interfaces"],
        ["Frequency-domain electric source/receiver only; source current/length are not silently normalized.", "Fixed 5-point quadrature; anisotropic dielectric/magnetic properties are not inferred."])
    add("GeoGravityTesseroid", "gravity_tesseroid", "harmonica", "harmonica.tesseroid_gravity",
        "Forward-model finite spherical density-contrast volumes with potential and radial-down acceleration bundled.",
        {"observations_lon_lat_radius": matrix(3, 32, number("Geocentric longitude/latitude degrees, radius m.", -1e7, 1e7)),
         "tesseroids_wesnbt": matrix(6, 8, number("West,east,south,north degrees and bottom,top radii m.", -1e7, 1e7)),
         "density_contrast_kg_m3": array(number("Signed density contrast kg/m^3.", -20000, 20000), 1, 8)},
        {"potential_j_kg": quantity("J/kg", None), "gravity_radial_down_m_s2": quantity("m/s^2", None)},
        dict(observations_lon_lat_radius=[[.5, .5, 6371000]], tesseroids_wesnbt=[[0, 1, 0, 1, 6300000, 6301000]], density_contrast_kg_m3=[1000]),
        "gravity-reference", "harmonica/_forward/tesseroid.py", "Finite spherical geometry is distinct from accepted Cartesian prism/point kernels.",
        "Independent full spherical shell oracle: M=4*pi*rho*(r_outer^3-r_inner^3)/3; outside potential=G*M/r>0 and radial-down gravity=G*M/r^2>0. Use G=6.6743e-11 with rho=1000kg/m3 and a nonzero shell thickness; numerical integration tolerance must be established, not asserted here.",
        ["Interior/boundary observer", "Dateline-wrapping/reversed bounds", "Thin <100m radial cell", "Geodetic height passed as radius"],
        ["Geocentric spherical coordinates; >=.01 degree angular extent; <=8 bodies and 32 observations."])
    xyz, fields, derivatives = [], [], []
    for east in (-50, 0, 50):
        for north in (-50, 0, 50):
            dx, dy, dz = east - 10, north + 20, 100
            radius = math.sqrt(dx*dx + dy*dy + dz*dz)
            c = 6.6743e-11 * 1e10 * 1e5
            xyz.append([east, north, 0]); fields.append(c*dz/radius**3 + 2)
            derivatives.append([-3*c*dz*dx/radius**5, -3*c*dz*dy/radius**5, c/radius**3-3*c*dz*dz/radius**5])
    add("GeoPotentialEulerSourceLocation", "potential_euler_source_location", "harmonica", "harmonica.EulerDeconvolution.fit",
        "Estimate one ideal-source location and constant base level from field values and all three measured spatial derivatives.",
        {"observations_enu_m": matrix(3, 256, coord, 5), "field": array(number(), 5, 256), "gradient_enu_per_m": matrix(3, 256, number(), 5),
         "structural_index": integer("Known physical homogeneity index; zero unsupported upstream.", 1, 3), "field_unit": field_unit},
        {"source_enu_m": quantity("m", 3), "base_level": quantity("input field unit"), "euler_residual": quantity("input field unit", None)},
        dict(observations_enu_m=xyz, field=fields, gradient_enu_per_m=derivatives, structural_index=2, field_unit="mGal"),
        "potential-interpretation", "harmonica/_euler_deconvolution.py", "A location/base-level inverse problem, not forward gravity or equivalent-source interpolation.",
        "Independent Newton point gravity derivatives generated analytically for source (10,-20,-100)m plus base 2mGal recover x=10m and base=2mGal, with the other coordinates fixed by the same independently derived field.",
        ["Rank-deficient gradient window", "Only four observations", "Condition number >1e8", "Unjustified structural index"],
        ["Single ideal homogeneous source per window; structural index conditions depth; no calibrated position uncertainty."])
    layer_schema = matrix(4, 32, number("thickness m,Vp m/s,Vs m/s,density kg/m^3.", 0, 1e6), 2)
    layer_values = [[1000, 3000, 1500, 2000], [0, 4500, 2500, 2500]]
    layer_common = {"layers_h_vp_vs_rho_si": layer_schema, "wave": enum(["rayleigh", "love"], "Polarization, not a separate tool."), "mode": integer("Modal order; fundamental=0.", 0, 2)}
    layer_example = dict(layers_h_vp_vs_rho_si=layer_values, wave="rayleigh", mode=0)
    add("GeoSurfaceWaveDispersion", "surface_wave_dispersion", "disba", "disba.PhaseDispersion.__call__; disba.GroupDispersion.__call__",
        "Return phase and group dispersion curves for a chosen supported Rayleigh/Love mode in solid elastic layers.",
        {**layer_common, "period_s": array(positive("Increasing period s.", .05, 1000), 1, 64)},
        {"phase_velocity_m_s": quantity("m/s", None), "group_velocity_m_s": quantity("m/s", None)}, {**layer_example, "period_s": [1, 2, 5]},
        "surface-waves", "disba/_dispersion.py", "Existing bulk elastic moduli and body-wave phase speeds do not solve layered surface-wave dispersion.",
        "Independent homogeneous Rayleigh secular polynomial at Vp/Vs=2 has c/Vs=0.9325259059311549; Vs=1500m/s gives c=1398.7888588967323m/s and group=phase. Separately require a genuinely layered Love traction-continuity benchmark.",
        ["Unstable elastic moduli", "Missing/negative thickness", "Absent modal root", "Unsorted periods"], ["Solid layers only; final thickness zero denotes halfspace; no silently missing modes."])
    obs = [[-50, -50, 0], [-50, 50, 0], [50, -50, 0], [50, 50, 0]]
    add("GeoPotentialEquivalentSources", "potential_equivalent_sources", "harmonica", "harmonica.EquivalentSources.fit; harmonica.EquivalentSources.predict",
        "Fit damped equivalent sources to irregular-altitude harmonic field measurements and predict specified positions.",
        {"observations_enu_m": points, "source_points_enu_m": matrix(3, 64, coord), "prediction_points_enu_m": points,
         "field": array(number(), 1, 128), "standard_deviation": array(positive("Measurement standard deviation in field units."), 1, 128),
         "field_unit": field_unit, "damping": positive("Explicit dimensionless upstream damping.", 1e-12, 100)},
        {"predicted_field": quantity("input field unit", None), "observation_residual": quantity("input field unit", None)},
        dict(observations_enu_m=obs, source_points_enu_m=[[0, 0, -100]], prediction_points_enu_m=[[0, 0, 100]],
             field=[1000/math.sqrt(15000)]*4, standard_deviation=[1]*4, field_unit="nT", damping=1e-10),
        "potential-interpretation", "harmonica/_equivalent_sources/cartesian.py", "Harmonic continuation/interpolation does not recover geological density/susceptibility and is not ordinary kriging.",
        "Independent one-source 1/r field with strength1000nT*m at z=-100m predicts 5nT at z=100m as damping tends to zero; nonzero damping bias must remain explicit.",
        ["Nonpositive errors", "Duplicate sources", "Sources above observations", "Coincident source/evaluation positions"],
        ["<=128 observations/predictions and 64 sources; below-plane restriction; no geological interpretation of source coefficients."])
    axis = [10*i for i in range(8)]
    grid_values = [[math.cos(2*math.pi*i/8) + .5*math.cos(2*math.pi*j/8) for i in range(8)] for j in range(8)]
    grid_fields = {"easting_m": array(coord, 4, 64), "northing_m": array(coord, 4, 64), "field_grid": matrix(64, 64),
                   "field_unit": field_unit, "periodic_grid_acknowledged": {"type": "boolean", "const": True}}
    grid_fields["field_grid"] = array(array(number(), 4, 64), 4, 64)
    grid_example = dict(easting_m=axis, northing_m=axis, field_grid=grid_values, field_unit="nT", periodic_grid_acknowledged=True)
    add("GeoPotentialUpwardContinuation", "potential_upward_continuation", "harmonica", "harmonica.upward_continuation",
        "Continue a regular planar potential-field grid upward with the harmonic spectral transfer.",
        {**grid_fields, "height_displacement_m": positive("Positive upward displacement m.", .001, 1e6)},
        {"continued_field": quantity("input field unit", None, None)}, {**grid_example, "height_displacement_m": 10},
        "potential-interpretation", "harmonica/_transformations.py", "Spatial harmonic continuation is neither gridding nor generic smoothing and has a physical height transfer.",
        "Independent Fourier harmonic wavelength80m continued10m attenuates by exp(-2*pi*10/80)=0.45593812776599624; constant component is unchanged.",
        ["Irregular grid", "Downward/zero displacement", "Missing samples", "Unacknowledged periodic boundary"], ["No padding, terrain-following geometry or downward continuation."])
    add("GeoMagneticReductionToPole", "magnetic_reduction_to_pole", "harmonica", "harmonica.reduction_to_pole",
        "Transform a planar magnetic anomaly to pole-equivalent inducing-field and magnetization directions.",
        {**grid_fields, "field_inclination_deg": number("Positive down inclination degrees.", -90, 90), "field_declination_deg": number("Clockwise from north degrees.", -180, 180),
         "magnetization_inclination_deg": number("Supplied positive-down magnetization inclination degrees.", -90, 90), "magnetization_declination_deg": number("Supplied magnetization declination degrees.", -180, 180)},
        {"pole_anomaly_nt": quantity("nT", None, None)}, {**grid_example, "field_inclination_deg": 60, "field_declination_deg": 20, "magnetization_inclination_deg": 50, "magnetization_declination_deg": 10},
        "potential-interpretation", "harmonica/_transformations.py", "This corrects directional magnetic phase, unlike continuation or susceptibility inversion.",
        "Independent pole/pole harmonic is unchanged with positive amplitude1nT. Also require a nonpolar Fourier projection reference using separate field and magnetization directions; pole-only equality is insufficient acceptance.",
        ["Either inclination within10deg of equator", "Nonuniform grid", "NaN cells"], ["Ill-conditioned equatorial RTP explicitly unsupported; no invented stabilization."])
    add("GeoDCFourElectrodeResponse", "dc_four_electrode_response", "geoana", "geoana.em.static.DipoleHalfSpace.potential",
        "Calculate a homogeneous halfspace four-electrode voltage using explicit current and potential electrode pairs.",
        {"current_electrodes_enu_m": matrix(3, 2, coord, 2), "potential_pairs_enu_m": array(matrix(3, 2, coord, 2), 1, 64),
         "resistivity_ohm_m": positive("Homogeneous resistivity ohm*m.", .001, 1e8), "current_a": number("Signed current entering A and exiting B, A.", -1e5, 1e5)},
        {"voltage_m_minus_n_v": quantity("V", None)}, dict(current_electrodes_enu_m=[[0, 0, 0], [30, 0, 0]], potential_pairs_enu_m=[[[10, 0, 0], [20, 0, 0]]], resistivity_ohm_m=100, current_a=1),
        "electromagnetic", "geoana/em/static/halfspace.py", "Static electric potential is not magnetic-source forward modelling or graph resistance distance.",
        "Independent Wenner geometry spacing10m,rho100ohm*m,I1A gives voltage=rho*I/(2*pi*a)=1.5915494309189535V.",
        ["Coincident potential/current electrode", "Above-ground electrode", "Reversed/malformed pairs"], ["Flat z<=0 homogeneous halfspace, no inversion or topography."])
    add("GeoGravityNormalEllipsoid", "gravity_normal_ellipsoid", "boule", "boule.WGS84.normal_gravity",
        "Calculate normal gravity including centrifugal acceleration at WGS84 geodetic positions and ellipsoidal heights.",
        {"geodetic_lon_lat_height": matrix(3, 256, number("Longitude/latitude degrees and ellipsoidal height m.", -180, 1e6))},
        {"normal_gravity_m_s2": quantity("m/s^2", None)}, dict(geodetic_lon_lat_height=[[0, 0, 0], [0, 90, 0]]),
        "gravity-reference", "boule", "Reference-ellipsoid gravity is not point/prism density-contrast gravity or slab correction.",
        "Independent WGS84 Somigliana constants: equatorial gravity9.7803253359m/s2 and polar9.8321849378m/s2 at zero ellipsoidal height.",
        ["Latitude outside90deg", "Negative height in this exterior profile", "Orthometric height without geoid conversion"], ["Fixed WGS84; no implicit geoid lookup or CRS conversion."])
    beam_data = [[math.sin(2*math.pi*5*(i*.01 - (x*.0001))) for i in range(512)] for x, y, z in [[0, 0, 0], [100, 0, 0], [0, 100, 0], [100, 100, 0]]]
    add("GeoSeismicArrayBeamforming", "seismic_array_beamforming", "obspy", "obspy.signal.array_analysis.array_processing",
        "Estimate apparent horizontal slowness, backazimuth and beam coherence from a synchronized local station array.",
        {"station_enu_m": matrix(3, 16, coord, 3), "velocity_station_time_m_s": array(array(number(), 64, 4096), 3, 16), "dt_s": dt,
         "fmin_hz": positive("Low band edge Hz.", .1, 1000), "fmax_hz": positive("High band edge Hz.", .2, 2000),
         "window_s": positive("Sliding analysis window s.", .1, 120), "slowness_bound_s_km": positive("Symmetric horizontal grid bound s/km.", .01, 5),
         "slowness_step_s_km": positive("Slowness grid step s/km; <=41 samples per axis.", .001, 1)},
        {"time_relpow_abspow_backaz_slowness": quantity("s,1,spectral (m/s)^2,degree,s/km", None, 5)},
        dict(station_enu_m=[[0, 0, 0], [100, 0, 0], [0, 100, 0], [100, 100, 0]], velocity_station_time_m_s=beam_data,
             dt_s=.01, fmin_hz=2, fmax_hz=10, window_s=2, slowness_bound_s_km=.2, slowness_step_s_km=.02),
        "array-kinematics", "obspy/signal/array_analysis.py", "Array wavefront estimation is distinct from single-trace picking and polarization.",
        "Independently delayed plane wave has east slowness0.1s/km and apparent speed10km/s; require direction convention and grid-resolution tolerance, not a self-generated upstream beam oracle.",
        ["Collinear stations", "Constant channel", "Too short low-frequency window", "Search grid >41x41"], ["Conventional beamformer, fixed half-window stride; absolute spectral power is not PSD."])
    add("GeoSeismicSTALTADetection", "seismic_sta_lta_detection", "obspy", "obspy.signal.trigger.classic_sta_lta; obspy.signal.trigger.trigger_onset",
        "Detect transient windows using classic energy STA/LTA and explicit hysteresis thresholds.",
        {"amplitude": series, "sta_samples": integer("STA sample count.", 1, 512), "lta_samples": integer("LTA sample count.", 2, 2048),
         "on_ratio": positive("Onset ratio, dimensionless.", 1, 1000), "off_ratio": positive("Offset ratio below onset.", .01, 1000)},
        {"sta_lta_ratio": quantity("1", None), "on_off_sample_inclusive": quantity("sample index", None, 2, item=integer("Sample index.", 0, 4095))},
        dict(amplitude=[1.]*80+[4.]*20+[1.]*60, sta_samples=5, lta_samples=40, on_ratio=3, off_ratio=1.5),
        "waveform-quality", "obspy/signal/trigger.py", "Energy-ratio event windows differ from AR phase picking and waveform-template matching.",
        "Constant nonzero amplitude after warm-up yields ratio1. A fully filled 5-sample high-amplitude window with amplitude4 against 35 previous unit samples gives STA16/LTA[(5*16+35)/40]=5.565217391304348.",
        ["STA>=LTA", "LTA>=record", "On threshold<=off threshold"], ["Ratios are not event probabilities; LTA warm-up is unusable support."])
    template = wave(32, 2)
    add("GeoSeismicTemplateDetection", "seismic_template_detection", "obspy", "obspy.signal.cross_correlation.correlation_detector",
        "Detect repeat events using a supplied multichannel waveform template and normalized similarity.",
        {"data_channel_time": array(array(number(), 64, 4096), 1, 8), "template_channel_time": array(array(number(), 8, 512), 1, 8), "dt_s": dt,
         "minimum_similarity": number("Positive normalized similarity threshold.", .01, 1), "minimum_separation_s": positive("Minimum peak separation s.", .001, 1000)},
        {"time_s_similarity": quantity("s,1", None, 2), "similarity": quantity("1", None)},
        dict(data_channel_time=[[0.]*40+template+[0.]*56], template_channel_time=[template], dt_s=.01, minimum_similarity=.8, minimum_separation_s=.1),
        "waveform-quality", "obspy/signal/cross_correlation.py", "Uses waveform shape and channel identity, not STA/LTA energy contrast.",
        "Independent copied template embedded at sample40 with dt=.01 gives alignment0.4s and normalized similarity1; a sign-reversed template is not a positive match.",
        ["Constant template", "Mismatched channel count", "Template longer than data"], ["One template per call, multichannel; no magnitude inference or external template library."])
    pol = [[2*v, v, .5*v] for v in wave()]
    add("GeoSeismicPolarization", "seismic_polarization", "obspy", "obspy.signal.polarization.flinn",
        "Estimate three-component particle-motion direction, rectilinearity and planarity in one supplied window.",
        {"displacement_zne_m": matrix(3, 4096, number("Z,N,E displacement m."), 32), "dt_s": dt},
        {"azimuth_deg": quantity("degree"), "incidence_deg": quantity("degree"), "rectilinearity": quantity("1"), "planarity": quantity("1")},
        dict(displacement_zne_m=pol, dt_s=.01), "array-kinematics", "obspy/signal/polarization.py",
        "Single-station motion eigensystem is distinct from array slowness and structural rock-fabric tensors.",
        "Independent rank-one ZNE sinusoid in direction(2,1,.5) has rectilinearity=1 and planarity=1; horizontal azimuth atan(.5/1)=26.56505117707799deg, modulo directional ambiguity.",
        ["Zero/constant motion", "Wrong component order", "Nonfinite samples"], ["Z,N,E order; principal-axis 180deg ambiguity, no automatic phase classification."])
    arrival = obj({"phase": string(), "time_s": number(), "ray_parameter_s_degree": number(), "takeoff_deg": number(), "incidence_deg": number(), "path_time_distance_depth": matrix(3, 4096)})
    add("GeoSeismicTauPRays", "seismic_taup_rays", "obspy", "obspy.taup.TauPyModel.get_ray_paths",
        "Predict ray paths and arrival properties in the local packaged iasp91 spherical reference model.",
        {"source_depth_km": number("Depth below surface km.", 0, 700), "distance_deg": positive("Source-receiver angular distance degrees.", .01, 180),
         "phases": array(enum(["P", "S", "Pn", "Sn", "PP", "SS", "PKP", "SKS"], "Fixed phase whitelist."), 1, 8)},
        {"arrivals": quantity("s,s/degree,degree,km", None, item=arrival)}, dict(source_depth_km=10, distance_deg=30, phases=["P", "S"]),
        "array-kinematics", "obspy/taup/tau.py", "Ray prediction in a reference model is not first-arrival velocity tomography or migration.",
        "Independent published iasp91 travel-time table is required for the supplied depth/distance; positive reference travel time must be sourced before acceptance. Path endpoint is independently constrained to distance30deg and source depth10km; these endpoint checks alone are not sufficient scientific acceptance.",
        ["Unknown phase name", "Source below700km", "Path/arrival budget exceeded"], ["Fixed iasp91 only in this adapter; no untrusted serialized velocity models."])
    nmo = [[math.sin(i*.2) for _ in range(3)] for i in range(128)]
    add("GeoSeismicNMO", "seismic_nmo", "bruges", "bruges.transform.nmo.nmo_correction",
        "Correct CMP hyperbolic normal moveout with supplied time-dependent NMO velocity and explicit interpolation support.",
        {"cmp_time_offset": array(array(number(), 1, 32), 8, 512), "offset_m": array(coord, 1, 32),
         "nmo_velocity_m_s": array(positive("NMO velocity m/s.", 100, 15000), 8, 512), "dt_s": dt},
        {"nmo_amplitude": quantity("normalized amplitude", None, None), "valid_support": quantity("boolean", None, None, item={"type": "boolean"})},
        dict(cmp_time_offset=nmo, offset_m=[0, 100, 200], nmo_velocity_m_s=[2000]*128, dt_s=.01),
        "array-kinematics", "bruges/transform/nmo.py", "Moveout time remapping is not wavelet generation or migration imaging.",
        "Independent hyperbola t0=.3s,offset800m,v2000m/s gives input time.5s. Zero-offset unit interior trace retains amplitude1 with support mask; include nonzero-offset pulse oracle in acceptance.",
        ["Velocity<=0", "Offset count mismatch", "Unmasked interpolation tails"], ["Upstream NMO file carries BSD-3-Clause attribution in addition to package Apache-2.0; no implicit stretch mute."])
    nullable_num = nullable(number())
    add("GeoSeismicComplexAttributes", "seismic_complex_attributes", "bruges", "bruges.attribute.complex.instantaneous_amplitude; instantaneous_phase; instantaneous_frequency",
        "Return trace envelope, phase and a support-masked Scheuer-Oldenburg interval-frequency attribute.",
        {"amplitude": series, "dt_s": dt, "amplitude_floor": positive("User-declared usable envelope floor in amplitude units.", 1e-20, 1e12)},
        {"envelope": quantity("normalized amplitude", None), "phase_rad": quantity("rad", None, item=nullable_num),
         "interval_frequency_hz": quantity("Hz", None, item=nullable_num), "frequency_valid": quantity("boolean", None, item={"type": "boolean"})},
        dict(amplitude=wave(256, 8, 2), dt_s=.01, amplitude_floor=1e-8), "array-kinematics", "bruges/attribute/complex.py",
        "Analytic signal attributes differ from coherence between traces and from supplied-wavelet forward reflectivity.",
        "Independent periodic sinusoid amplitude2 and8 cycles/2.56s has envelope2 and frequency3.125Hz; low-amplitude and >=pi/2 increment intervals must be null.",
        ["Amplitude floor too large leaves no valid phase", "NaN sample", "Aliased phase increment"], ["No wrapped-phase SciPy variant; N-1 frequencies, explicit null validity and FFT boundary limitations."])
    coh = [[[1., 2., 1., -1.] for _ in range(2)] for _ in range(2)]
    add("GeoSeismicWindowCoherence", "seismic_window_coherence", "bruges", "bruges.attribute.discontinuity.marfurt",
        "Measure direct Marfurt coherence inside a supplied 3-D survey window, without the defective high-level wrapper.",
        {"inline_crossline_time_window": tensor(16, 16, 128)}, {"coherence": quantity("1")},
        dict(inline_crossline_time_window=coh), "array-kinematics", "bruges/attribute/discontinuity.py",
        "Multitrace waveform coherence is not a single-trace envelope or generic vector correlation.",
        "Four identical traces [1,2,1,-1] give coherence28/(28+1e-12), approximately1; pairwise opposite traces sum to zero. Preserve upstream epsilon in the independent formula.",
        ["Only one trace", "Zero/tiny total energy", "Ragged volume"], ["Input is one explicit aligned analysis window, not an unbounded cube scan."])
    add("GeoPotentialEdgeAttributes", "potential_edge_attributes", "harmonica", "harmonica.total_gradient_amplitude; harmonica.tilt_angle",
        "Compute bundled total-gradient amplitude and tilt of a complete planar potential-field anomaly grid.",
        {**grid_fields, "gradient_floor_per_m": positive("Usable gradient floor, field units/m.", 1e-20, 1e10)},
        {"total_gradient": quantity("field unit/m", None, None), "tilt_rad": quantity("rad", None, None, item=nullable_num), "tilt_valid": quantity("boolean", None, None, item={"type": "boolean"})},
        {**grid_example, "gradient_floor_per_m": 1e-9}, "potential-interpretation", "harmonica/_transformations.py",
        "Field-edge diagnostics are not Euler ideal-source depth estimates or optical edge-image processing.",
        "Independent single Fourier harmonic A*cos(k*x) has total gradient A*k; A1nT,wavelength80m gives0.07853981633974483nT/m. Constant-field tilt is undefined/null, never zero-imputed.",
        ["Zero-gradient tilt treated as finite evidence", "Irregular grid", "Missing cells"], ["Periodic grid and spectral edge effects; gradients do not establish geological contacts."])
    stations = [[0, 0, 0], [100, 0, 0], [0, 100, 0], [100, 100, 0]]
    displacement = [[[1e-5*x*i/31, .5e-5*y*i/31, (-2e-6*x+3e-6*y)*i/31] for x,y,z in stations] for i in range(32)]
    add("GeoSeismicArrayStrainRotation", "seismic_array_strain_rotation", "obspy", "obspy.signal.array_analysis.array_rotation_strain",
        "Estimate small dynamic ground strain/rotation from synchronized 3C array displacement and supplied measurement error.",
        {"station_enu_m": matrix(3, 16, coord, 3), "displacement_time_station_enu_m": array(matrix(3, 16, number("Displacement m."), 3), 2, 256),
         "vp_m_s": positive("P speed m/s.", 100, 15000), "vs_m_s": positive("S speed m/s.", 50, 10000), "displacement_error_m": positive("Independent component displacement error sigma m.", 1e-12, 1)},
        {"strain_tensor": quantity("1", None, 3, 3), "rotation_enu_rad": quantity("rad", None, 3), "misfit_ratio": quantity("1", None, item=nullable_num), "rotation_sigma_rad": quantity("rad", 3)},
        dict(station_enu_m=stations, displacement_time_station_enu_m=displacement, vp_m_s=3000, vs_m_s=1500, displacement_error_m=1e-6),
        "array-kinematics", "obspy/signal/array_analysis.py", "Ground-motion spatial gradients and rotations are distinct from geological finite-strain tensors and array beam direction.",
        "Independent affine displacement u_x=1e-5*x yields e_xx=1e-5 at the final sample; rigid rotation and free-surface-constrained gradients need separate analytic references. Zero differential motion has undefined misfit ratio but finite zero strain.",
        ["Collinear/nonflat array", "Nonpositive elastic bulk modulus", "Recovered strain/rotation>.01", "Shape mismatch"], ["Flat free surface, small-strain assumption; covariance is conditional on supplied error model."])
    add("GeoGravityBouguerSlab", "gravity_bouguer_slab", "harmonica", "harmonica.bouguer_correction",
        "Calculate explicit-density land and bathymetric infinite-slab gravity corrections.",
        {"topography_m": array(number("Height positive up m, bathymetry negative.", -12000, 10000), 1, 256),
         "crust_density_kg_m3": positive("Crust density kg/m3.", 1000, 5000), "water_density_kg_m3": positive("Water density kg/m3, less than crust.", 100, 2000)},
        {"slab_correction_mgal": quantity("mGal", None)}, dict(topography_m=[100, -100], crust_density_kg_m3=2670, water_density_kg_m3=1040),
        "gravity-reference", "harmonica/_gravity_corrections.py", "Infinite-slab reference reduction is not finite-prism terrain modelling or normal ellipsoid gravity.",
        "Independent land slab g=2*pi*G*rho*h, G6.6743e-11,rho2670,h100, gives11.1968756063mGal; bathymetry uses explicit rock-water density difference and signed height.",
        ["Water density>=crust", "Nonfinite height"], ["Returns signed correction without silently changing observed anomalies."])
    layer_load = obj({"thickness_m": array(number("Overlying layer thickness m.", 0, 20000), 1, 256), "density_kg_m3": positive("Layer bulk density kg/m3.", 1, 5000)})
    add("GeoCrustAiryMoho", "crust_airy_moho", "harmonica", "harmonica.isostatic_moho_airy",
        "Estimate Airy-compensated Moho depth from basement relief and explicitly supplied surface layers.",
        {"basement_height_m": array(number("Crystalline basement height m.", -20000, 10000), 1, 256), "overlying_layers": array(layer_load, 0, 8),
         "crust_density_kg_m3": positive("Crust density kg/m3.", 1000, 4000), "mantle_density_kg_m3": positive("Mantle density kg/m3, above crust.", 2000, 6000), "reference_depth_m": positive("Reference Moho depth m.", 1000, 100000)},
        {"moho_depth_m": quantity("m below reference level", None)}, dict(basement_height_m=[1200], overlying_layers=[dict(thickness_m=[200], density_kg_m3=2300)], crust_density_kg_m3=2800, mantle_density_kg_m3=3300, reference_depth_m=30000),
        "gravity-reference", "harmonica/_isostasy.py", "Mass-balance compensation is not querying an external Moho map or elastic plate flexure.",
        "Independent column mass balance: 30000+(2800*1200+2300*200)/(3300-2800)=37640m.",
        ["Mantle density<=crust", "Negative load thickness", "Moho above basement"], ["Airy local compensation only; no claim of measured crustal thickness."])
    add("GeoEMConductiveSphere", "em_conductive_sphere", "geoana", "geoana.em.static.ElectrostaticSphere.electric_field; ElectrostaticSphere.current_density",
        "Calculate internal/external total and secondary DC electric fields and current density of a conducting sphere.",
        {"observations_enu_m": points, "center_enu_m": array(coord, 3, 3), "radius_m": positive("Sphere radius m.", .001, 1e6),
         "sphere_conductivity_s_m": positive("Sphere conductivity S/m.", 1e-8, 1e6), "background_conductivity_s_m": positive("Background conductivity S/m.", 1e-8, 1e6),
         "primary_electric_enu_v_m": array(number("Uniform incident E field V/m.", -1e6, 1e6), 3, 3)},
        {"total_electric_v_m": quantity("V/m", None, 3), "secondary_electric_v_m": quantity("V/m", None, 3), "total_current_a_m2": quantity("A/m^2", None, 3)},
        dict(observations_enu_m=[[0, 0, 0], [2, 0, 0]], center_enu_m=[0, 0, 0], radius_m=1, sphere_conductivity_s_m=2, background_conductivity_s_m=1, primary_electric_enu_v_m=[1, 0, 0]),
        "electromagnetic", "geoana/em/static/sphere.py", "DC conductivity contrast is not a static magnetized sphere/dipole or layered inductive EM response.",
        "Independent sphere boundary solution: E_inside=3*sigma_bg/(sigma_s+2*sigma_bg)*E0=.75V/m; J_inside=sigma_s*E_inside=1.5A/m2.",
        ["Zero primary field", "Nonpositive conductivity", "Observer exactly on interface"], ["Uniform whole-space incident field, no time-dependent induction."])
    add("GeoMagneticWirePath", "magnetic_wire_path", "geoana", "geoana.em.static.LineCurrentWholeSpace.magnetic_flux_density",
        "Calculate vector magnetic induction of an explicitly closed piecewise-linear current loop.",
        {"closed_loop_nodes_enu_m": matrix(3, 65, coord, 4), "observations_enu_m": points, "current_a": number("Signed steady current A along node order.", -1e6, 1e6)},
        {"magnetic_enu_t": quantity("T", None, 3)}, dict(closed_loop_nodes_enu_m=[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0],[-1,-1,0]], observations_enu_m=[[0,0,0]], current_a=1),
        "electromagnetic", "geoana/em/static/wholespace.py", "Explicit finite survey-source wire geometry differs from an ideal magnetic point dipole.",
        "Independent square-loop center B=2*sqrt(2)*mu0*I/(pi*a), half-side a1m,I1A; Bz positive about1.13137085e-6T. Use the pinned SciPy mu0 in the acceptance tolerance.",
        ["Open loop", "Zero-length segment", "Observer on any segment axis including extension"], ["Filamentary current; line-axis upstream singularity is rejected, not silently patched."])
    ar_data = []
    for i in range(2048):
        t = i*.01
        p = math.sin(2*math.pi*5*t)*math.exp(-((t-5)/.25)**2)
        s = math.sin(2*math.pi*4*t)*math.exp(-((t-10)/.5)**2)
        ar_data.append([p+1e-5*math.sin(t), .2*p+s+1e-5*math.cos(t), .1*p+.8*s+1e-5*math.sin(2*t)])
    add("GeoSeismicARPhasePick", "seismic_ar_phase_pick", "obspy", "obspy.signal.trigger.ar_pick",
        "Estimate P/S onset times in a supplied three-component record with a fixed AR-AIC/STA-LTA profile.",
        {"velocity_zne_m_s": matrix(3, 4096, number("Z,N,E velocity m/s."), 256), "dt_s": positive("Sample interval seconds; resolves fixed .1s windows.", .001, .01),
         "fmin_hz": positive("Low prefilter Hz.", .1, 100), "fmax_hz": positive("High prefilter Hz.", .2, 200)},
        {"p_onset_s": quantity("s", item=nullable_num), "s_onset_s": quantity("s", item=nullable_num)},
        dict(velocity_zne_m_s=ar_data, dt_s=.01, fmin_hz=1, fmax_hz=15), "waveform-quality", "obspy/signal/trigger.py",
        "AR phase-onset inference differs from event-window STA/LTA and repeat-template detection.",
        "Independent piecewise-onset 3C signals must place P at5s and S at10s with an explicitly justified nonzero timing tolerance. The smooth pulse fixture is an input example, not proof that an AR pick equals its peak; false-pick calibration remains pending.",
        ["Record<8s", "Constant component", "Band above Nyquist", "Returned nonpositive/out-of-record onset"], ["Fixed windows/orders; invalid picks returned null, no invented confidence interval."])
    add("GeoSeismicProbabilisticNoise", "seismic_probabilistic_noise", "obspy", "obspy.signal.spectral_estimation.PPSD.add",
        "Accumulate calibrated acceleration PSD segments and bounded histogram counts for one stationary instrument epoch.",
        {**paz_fields, "segment_s": positive("PSD segment length s; at least256 samples.", 4, 3600), "period_min_s": positive("Shortest analyzed period s.", .001, 100), "period_max_s": positive("Longest period s, below segment/8.", .002, 1000)},
        {"period_center_s": quantity("s", None), "segment_psd_db": quantity("dB re (m/s^2)^2/Hz", None, None), "db_edges": quantity("dB", None),
         "histogram_counts": quantity("count", None, None, item=integer("Count.", 0, 64)), "out_of_histogram_count": quantity("count", None, item=integer("Count.", 0, 64))},
        {**paz, "counts": wave(8192, 256, 1e-5), "segment_s": 32, "period_min_s": .04, "period_max_s": 2},
        "waveform-quality", "obspy/signal/spectral_estimation.py", "A calibrated station-noise distribution is not bandpass filtering or single-window FFT magnitude.",
        "Independent calibration scaling: doubling sensitivity reduces PSD by6.020599913279624dB (power factor4). Independently derive finite-window sinusoidal PSD and histogram bins before acceptance; no executed numerical reference is claimed.",
        ["Response epoch changes within record", "Incomplete segment", "Constant record", "Unresolved period band"], ["Fixed -220..-20dB bins and50% overlap; out-of-range counts explicit, overlapping segments not independent probabilities."])
    add("GeoSeismicWaveformTFMisfit", "seismic_waveform_tf_misfit", "obspy", "obspy.signal.tf_misfit.tfem; obspy.signal.tf_misfit.tfpm",
        "Separate amplitude-envelope and phase discrepancies of aligned seismic waveforms using a fixed Morlet time-frequency transform.",
        {"synthetic": array(number(), 32, 512), "observed": array(number(), 32, 512), "dt_s": dt,
         "fmin_hz": positive("Low frequency Hz.", .01, 1000), "fmax_hz": positive("High frequency Hz.", .02, 2000)},
        {"frequency_hz": quantity("Hz", None), "envelope_misfit": quantity("1", 16, None), "phase_misfit": quantity("pi-normalized weighted phase", 16, None, item=nullable_num), "phase_valid": quantity("boolean", 16, None, item={"type":"boolean"})},
        dict(synthetic=wave(128, 8, 2), observed=wave(128, 8), dt_s=.01, fmin_hz=2, fmax_hz=20), "waveform-quality", "obspy/signal/tf_misfit.py",
        "Time-frequency envelope/phase evidence differs from a scalar waveform correlation or FFT.",
        "Independent scaling synthetic=2*observed leaves supported phase misfit0 and yields global-normalized envelope misfit maximum1. Constant time/phase shifts need separate analytic wavelet benchmarks.",
        ["Zero observed reference", "Mismatched samples", "Unsupported low-energy phase", "Frequency above Nyquist"], ["16 log frequencies, w0=6; finite-record wavelet boundary effects are not removed."])
    add("GeoSeismicRadiationPattern", "seismic_radiation_pattern", "obspy", "obspy.core.event.source.farfield",
        "Calculate normalized P/S radiation vectors of a general symmetric Cartesian seismic moment tensor.",
        {"moment_tensor_enu_nm": matrix(3, 3, number("Moment tensor N*m.", -1e30, 1e30), 3), "direction_enu": points},
        {"p_vector": quantity("1", None, 3), "s_vector": quantity("1", None, 3), "tensor_frobenius_nm": quantity("N*m")},
        dict(moment_tensor_enu_nm=[[1,0,0],[0,1,0],[0,0,1]], direction_enu=[[1,0,0],[0,1,0],[0,0,1]]),
        "array-kinematics", "obspy/core/event/source.py", "Radiation projections for supplied general tensors are not creation of a double-couple tensor or MoPaD eigendecomposition.",
        "Independent normalized isotropic tensor I/sqrt(3) gives P vector parallel to direction with amplitude1/sqrt(3)=.5773502691896258 and zero S. Also require a mixed ISO/DC/CLVD tensor against direct tensor contractions, not MoPaD.",
        ["Asymmetric/zero tensor", "Zero direction vector", "Confused spherical/ENU basis"], ["No MoPaD eigen ordering; Frobenius normalization, not scalar seismic moment; no geometric spreading."])
    add("GeoSurfaceWaveEigenfunctions", "surface_wave_eigenfunctions", "disba", "disba._cps.swegn96",
        "Calculate layer-interface normalized surface-wave displacement shapes using the public CPS kernel and explicit depth mapping.",
        {**layer_common, "period_s": positive("Mode period s.", .05, 1000)},
        {"interface_depth_m": quantity("m", None), "relative_displacement": quantity("1", None, None)},
        {**layer_example, "period_s": 2}, "surface-waves", "disba/_cps/_swegn96.py",
        "Mode displacement versus depth is distinct from phase/group dispersion and its parameter sensitivities.",
        "Independent layered Love sine/cosine plus halfspace exponential displacement and traction-continuity solution must match modal interface ratios. Declared peak-displacement normalization is1; depth interfaces for [1000,0]m are[0,1000]m. Normalization alone is not scientific acceptance.",
        ["Absent mode", "Invalid solid layers", "Zero modal normalization", "Using high-level defective depth labels"], ["Only displacement components, not dimensionally ambiguous traction; public kernel output preserved before explicit normalization."])
    add("GeoSurfaceWaveSensitivity", "surface_wave_sensitivity", "disba", "disba.PhaseSensitivity.__call__",
        "Return bundled layerwise phase-speed sensitivities to thickness, Vp, Vs and density for inversion design.",
        {**layer_common, "period_s": positive("Mode period s.", .05, 1000)},
        {"dc_dthickness_s_inv": quantity("1/s", None, item=nullable_num), "dc_dvp": quantity("1", None), "dc_dvs": quantity("1", None),
         "dc_ddensity_m4_kg_s": quantity("m^4/(kg*s)", None), "interface_depth_m": quantity("m", None)},
        {**layer_example, "period_s": 2}, "surface-waves", "disba/_sensitivity.py",
        "Physical derivatives for model resolution/inversion design are not another dispersion-mode alias.",
        "Independent homogeneous Rayleigh secular-equation implicit derivatives provide nonzero Vp/Vs sensitivities. Uniform elastic-velocity scaling obeys sum(Vp*dc/dVp+Vs*dc/dVs)=c>0; require an independent layered derivative reference and perturbation convergence, not only same-kernel finite differences.",
        ["Nonpositive material properties", "Missing mode", "Interpreting halfspace thickness as free parameter"], ["dp=.01 finite perturbation; halfspace-thickness derivative null; no posterior uncertainty."])
    inverse_fields = {"max_iterations": integer("Maximum bounded outer iterations.", 1, 20), "regularization_beta": positive("Explicit fixed data/model tradeoff beta in upstream objective.", 1e-12, 1e8)}
    mesh_fields = {k: array(number("Strictly increasing tensor-cell edge m.", -1e5, 1e5), 3, 7) for k in ("x_edges_m", "y_edges_m", "z_edges_m")}
    mesh_example = dict(x_edges_m=[-100,-20,20,100], y_edges_m=[-100,-20,20,100], z_edges_m=[-100,-40,-10,0], max_iterations=5, regularization_beta=.01)
    geometry = [[[-30,0,0],[30,0,0],[-10,0,0],[10,0,0]], [[0,-30,0],[0,30,0],[0,-10,0],[0,10,0]]]
    electrode_fields = {"electrode_abmn_enu_m": array(matrix(3,4,coord,4), 1, 32), "source_current_a": array(number("Signed nonzero injected current A.", -1000, 1000), 1, 32)}
    conductivity_fields = {"starting_conductivity_s_m": array(positive("Initial conductivity S/m.", 1e-8, 100),1,216),
                           "conductivity_lower_s_m": positive("Conductivity lower bound S/m.", 1e-8, 10), "conductivity_upper_s_m": positive("Conductivity upper bound S/m.", 1e-7, 100)}
    inverse_limit = ["Fixed CPU SimPEG ProjectedGNCG, bounded mesh and iterations; no caller solver/callback/code.", "Convergence may be iteration_limit or uncertified stop. Conditional regularized estimate, not unique geology or posterior uncertainty.", "Private pinned environment and parent worker registration required; not run, deployed, submitted or AI-Lab certified."]
    add("GeoDCResistivityInversion", "dc_resistivity_inversion", "simpeg", "simpeg.electromagnetics.static.resistivity.Simulation3DNodal; simpeg.inversion.BaseInversion.run",
        "Invert surface-electrode voltages for positive conductivity/resistivity on a supplied bounded flat-surface tensor mesh.",
        {**mesh_fields, **electrode_fields, **conductivity_fields, **inverse_fields, "voltage_v": array(number("Signed M-N voltage V."),1,32), "standard_deviation_v": array(positive("Voltage error sigma V."),1,32)},
        {"cell_centers_enu_m": quantity("m",None,3), "resistivity_ohm_m": quantity("ohm*m",None), "predicted_voltage_v": quantity("V",None), "residual_v": quantity("V",None)},
        {**mesh_example, "electrode_abmn_enu_m":geometry, "source_current_a":[1,1], "starting_conductivity_s_m":[.01]*27,
         "conductivity_lower_s_m":1e-5, "conductivity_upper_s_m":1, "voltage_v":[100/(40*math.pi)]*2, "standard_deviation_v":[.05,.05]},
        "electromagnetic", "simpeg/electromagnetics/static/resistivity/simulation.py",
        "GeoDCFourElectrodeResponse is forward homogeneous conduction; this estimates spatial conductivity from data. Dimensions are not split into separate tools.",
        "Independent homogeneous halfspace rho100ohm*m yields .7957747154594768V for A/B=-30/+30m,M/N=-10/+10m,I1A. Finite-domain boundary and mesh error must be quantified against that reference before interpreting recovered100ohm*m; add heterogeneous benchmark.",
        ["Electrodes too close to side boundary", "Duplicate electrodes", "Starting model outside bounds", "Nonpositive errors", "Uncertified convergence"], inverse_limit)
    add("GeoIPChargeabilityInversion", "ip_chargeability_inversion", "simpeg", "simpeg.electromagnetics.static.induced_polarization.Simulation3DNodal; simpeg.inversion.BaseInversion.run",
        "Invert apparent chargeability for a bounded linearized IP model conditional on supplied positive DC background conductivity.",
        {**mesh_fields, **electrode_fields, **inverse_fields, "background_conductivity_s_m":array(positive("Known background conductivity S/m.",1e-8,100),1,216),
         "starting_chargeability_v_v":array(number("Initial volumetric chargeability V/V.",1e-6,.299),1,216), "chargeability_upper_v_v":positive("Upper linearized chargeability bound V/V.",.001,.3),
         "apparent_chargeability_v_v":array(number("Signed normalized apparent chargeability V/V.",-1,1),1,32), "standard_deviation_v_v":array(positive("Chargeability sigma V/V.",1e-8,1),1,32)},
        {"cell_centers_enu_m":quantity("m",None,3), "chargeability_v_v":quantity("V/V",None), "predicted_chargeability_v_v":quantity("V/V",None), "residual_v_v":quantity("V/V",None)},
        {**mesh_example,"electrode_abmn_enu_m":geometry,"source_current_a":[1,1],"background_conductivity_s_m":[.01]*27,
         "starting_chargeability_v_v":[.05]*27,"chargeability_upper_v_v":.3,"apparent_chargeability_v_v":[.1,.1],"standard_deviation_v_v":[.005,.005]},
        "electromagnetic", "simpeg/electromagnetics/static/induced_polarization/simulation.py",
        "Recovers IP chargeability rather than DC conductivity from distinct normalized secondary observations; no dimension variant counted.",
        "Independent spatially uniform linearized eta=.1 gives apparent chargeability.1V/V independent of homogeneous electrode geometry when DC voltage is nonzero. Include heterogeneous IP and uncertain-background references in acceptance.",
        ["DC voltage near zero", "Missing/nonpositive conductivity background", "mV/V supplied without conversion", "Eta outside linearized bounds"], inverse_limit)
    layered_inverse = {**inverse_fields, **conductivity_fields, "finite_layer_thickness_m":array(positive("Finite-layer thickness m.",1,10000),1,15),
                       "halfspace_regularization_length_m":positive("Numerical regularization metric length m for final halfspace, not physical thickness.",1,100000)}
    layered_example = dict(max_iterations=5,regularization_beta=.01,starting_conductivity_s_m=[.01,.02],conductivity_lower_s_m=1e-5,
                           conductivity_upper_s_m=1,finite_layer_thickness_m=[100],halfspace_regularization_length_m=500)
    add("GeoFDEMConductivityInversion", "fdem_conductivity_inversion", "simpeg", "simpeg.electromagnetics.frequency_domain.Simulation1DLayered; simpeg.inversion.BaseInversion.run",
        "Invert complex secondary magnetic H observations for layered conductivity with a fixed vertical magnetic-dipole survey.",
        {**layered_inverse,"frequency_hz":array(positive("Increasing frequency Hz.",.01,1e5),2,32),"offset_m":positive("Horizontal transmitter-receiver offset m.",1,1e5),
         "height_m":positive("Source and receiver height above flat ground m.",.1,10000),"moment_a_m2":positive("Vertical source magnetic moment A*m2.",1e-6,1e9),
         "secondary_h_real_imag_a_m":matrix(2,32,number("Real/imaginary secondary H, A/m."),2),"standard_deviation_a_m":matrix(2,32,positive("Component error sigma A/m."),2)},
        {"conductivity_s_m":quantity("S/m",None),"predicted_real_imag_a_m":quantity("A/m",None,2),"residual_real_imag_a_m":quantity("A/m",None,2)},
        {**layered_example,"frequency_hz":[10,100,1000],"offset_m":100,"height_m":10,"moment_a_m2":1,
         "secondary_h_real_imag_a_m":[[1e-8,-1e-8],[2e-8,-2e-8],[3e-8,-3e-8]],"standard_deviation_a_m":[[1e-9,1e-9]]*3},
        "electromagnetic", "simpeg/electromagnetics/frequency_domain/simulation_1d.py",
        "Empymod candidate is forward response; this estimates conductivity from complex FDEM data with supplied errors.",
        "Independent homogeneous halfspace magnetic-dipole Hankel-integral benchmark at sigma=.01S/m is required before acceptance, with nonzero real/imaginary reference values and sign convention. Input fixture observations are synthetic placeholders for authoring, not claimed analytic truth or passing acceptance.",
        ["Total field passed as secondary", "Nonpositive component error", "Wrong complex ordering", "Missing final-halfspace prior metric"], inverse_limit)
    add("GeoTDEMConductivityInversion", "tdem_conductivity_inversion", "simpeg", "simpeg.electromagnetics.time_domain.Simulation1DLayered; simpeg.inversion.BaseInversion.run",
        "Invert central-loop ideal-step-off dBz/dt observations for layered conductivity with explicit uncertainties and bounds.",
        {**layered_inverse,"off_time_s":array(positive("Ordered times after ideal shutoff, seconds.",1e-6,10),2,32),"height_m":positive("Loop/receiver height m.",.1,1000),
         "loop_radius_m":positive("Horizontal single-turn loop radius m.",1,1000),"current_a":positive("Pre-shutoff loop current A.",1e-6,1e4),
         "dbdt_t_s":array(number("Signed vertical dB/dt T/s."),2,32),"standard_deviation_t_s":array(positive("dB/dt sigma T/s."),2,32)},
        {"conductivity_s_m":quantity("S/m",None),"predicted_dbdt_t_s":quantity("T/s",None),"residual_t_s":quantity("T/s",None)},
        {**layered_example,"off_time_s":[.001,.003,.01],"height_m":1,"loop_radius_m":20,"current_a":1,"dbdt_t_s":[-1e-6,-2e-7,-1e-8],"standard_deviation_t_s":[1e-7,2e-8,1e-9]},
        "electromagnetic", "simpeg/electromagnetics/time_domain/simulation_1d.py",
        "Causal loop turn-off decay inversion is not a renamed complex-frequency FDEM observation or a forward EM call.",
        "Independent conductive halfspace late-time central-loop dB/dt has t^(-5/2) asymptotic amplitude scaling: ratio at t and2t is2^(5/2)=5.656854249492381. Absolute nonzero halfspace and heterogeneous benchmarks remain required; asymptotic scaling alone is insufficient.",
        ["Times at/before shutoff", "Voltage substituted for dB/dt", "Finite-ramp data without forward ramp", "Nonpositive uncertainty"], inverse_limit+["Ideal instantaneous step-off only; no instrument gate-average or voltage-area conversion."])
    inv_obs = [[-50,-50,50],[-50,50,50],[50,-50,50],[50,50,50],[0,0,50]]
    add("GeoGravityDensityInversion", "gravity_density_inversion", "simpeg", "simpeg.potential_fields.gravity.Simulation3DIntegral; simpeg.inversion.BaseInversion.run",
        "Recover bounded density contrast from upward-positive gravity anomalies on a supplied subsurface tensor mesh.",
        {**mesh_fields,**inverse_fields,"observations_enu_m":points,"gravity_up_mgal":array(number("Upward-positive gz mGal."),1,128),
         "standard_deviation_mgal":array(positive("Gravity sigma mGal."),1,128),"starting_density_contrast_kg_m3":array(number("Signed initial density contrast kg/m3.",-5000,5000),1,216),
         "density_lower_kg_m3":number("Lower density-contrast bound kg/m3.",-5000,5000),"density_upper_kg_m3":number("Upper density-contrast bound kg/m3.",-5000,5000)},
        {"cell_centers_enu_m":quantity("m",None,3),"density_contrast_kg_m3":quantity("kg/m3",None),"predicted_gravity_up_mgal":quantity("mGal",None),"residual_mgal":quantity("mGal",None)},
        {**mesh_example,"observations_enu_m":inv_obs,"gravity_up_mgal":[-.1,-.1,-.1,-.1,-.2],"standard_deviation_mgal":[.01]*5,
         "starting_density_contrast_kg_m3":[0]*27,"density_lower_kg_m3":-1000,"density_upper_kg_m3":1000},
        "gravity-reference", "simpeg/potential_fields/gravity/simulation.py",
        "Existing source gravity is forward; equivalent sources represent field interpolation, not a bounded volumetric density model.",
        "Independent Newton sphere/prism anomaly reference is required with explicit kg/m3-to-g/cc conversion1000:1; signed upward gravity must be negative above positive mass. Recovery is nonunique: assess residual and regularized optimum, not unsupported exact voxel truth.",
        ["Observer inside source mesh", "Density bounds reversed", "Down-positive data without explicit conversion", "Nonpositive errors"], inverse_limit)
    add("GeoMagneticSusceptibilityInversion", "magnetic_susceptibility_inversion", "simpeg", "simpeg.potential_fields.magnetics.Simulation3DIntegral; simpeg.inversion.BaseInversion.run",
        "Recover bounded induced-only scalar susceptibility from TMI anomalies using a supplied inducing field.",
        {**mesh_fields,**inverse_fields,"observations_enu_m":points,"tmi_nt":array(number("TMI anomaly nT."),1,128),"standard_deviation_nt":array(positive("TMI sigma nT."),1,128),
         "starting_susceptibility_si":array(positive("Initial scalar susceptibility, dimensionless SI.",1e-8,.099),1,216),"susceptibility_upper_si":positive("Upper low-susceptibility linear bound SI.",.0001,.1),
         "inducing_field_nt":positive("Inducing field magnitude nT.",1000,100000),"inclination_deg":number("Inclination positive down degrees.",-90,90),"declination_deg":number("Declination clockwise north degrees.",-180,180)},
        {"cell_centers_enu_m":quantity("m",None,3),"susceptibility_si":quantity("1 SI",None),"predicted_tmi_nt":quantity("nT",None),"residual_nt":quantity("nT",None)},
        {**mesh_example,"observations_enu_m":inv_obs,"tmi_nt":[1,1,1,1,2],"standard_deviation_nt":[.1]*5,"starting_susceptibility_si":[.001]*27,
         "susceptibility_upper_si":.05,"inducing_field_nt":50000,"inclination_deg":60,"declination_deg":0},
        "potential-interpretation", "simpeg/potential_fields/magnetics/simulation.py",
        "Estimates material susceptibility; RTP/edge attributes transform fields and accepted magnetized-prism tools only predict observations.",
        "Independent induced sphere dipole projection with prescribed susceptibility.01 SI and known inducing field provides nonzero TMI oracle; exact voxel recovery is not assumed. Require residual, bounds, sign and stationarity checks with nonzero anomalies.",
        ["Remanence-dependent interpretation", "Strong susceptibility beyond linear regime", "Zero field magnitude", "Observation in source volume"], inverse_limit)
    solver_fields = {"max_iterations":integer("Maximum LSQR iterations.",1,100),"damping":positive("Explicit LSQR Tikhonov damping.",1e-8,100)}
    wav_fields = {"wavelet":array(number("Centered source wavelet in calibrated normalized amplitude.",-1e6,1e6),3,65)}
    x = [-100,-50,0,50,100]; z = [100,150,200,250,300]; time = [i*.01 for i in range(101)]
    src = [[-50,0],[50,0]]; rec = [[v,0] for v in (-100,-75,-50,-25,0,25,50,75)]
    gather = [[[max(0,1-abs(t-(math.hypot(s[0],200)+math.hypot(r[0],200))/2000)/.01) for t in time] for r in rec] for s in src]
    add("GeoSeismicLeastSquaresMigration", "seismic_least_squares_migration", "pylops", "pylops.waveeqprocessing.LSM.solve",
        "Recover a regularized reflectivity image with fixed NumPy Kirchhoff LSM and constant-background analytic travel times.",
        {**solver_fields,**wav_fields,"x_m":array(coord,3,32),"depth_m":array(number("Positive depth m.",0,1e5),3,32),"time_s":array(number("Uniform time s starting zero.",0,1000),32,512),
         "sources_x_depth_m":matrix(2,8,coord),"receivers_x_depth_m":matrix(2,32,coord),"background_velocity_m_s":positive("Constant background speed m/s.",100,15000),"shot_gather":tensor(8,32,512)},
        {"reflectivity_image":quantity("upstream image amplitude",None,None),"predicted_gather":quantity("normalized amplitude",None,None,None)},
        dict(max_iterations=30,damping=.01,wavelet=[0,1,0],x_m=x,depth_m=z,time_s=time,sources_x_depth_m=src,receivers_x_depth_m=rec,background_velocity_m_s=2000,shot_gather=gather),
        "seismic-imaging", "pylops/waveeqprocessing/lsm.py", "Migration images subsurface reflectors; NMO only realigns travel times and forward reflectivity assumes known interfaces.",
        "Independent point reflector at x0,z200m in v2000m/s has zero-offset two-way time.2s; other source/receiver arrivals follow Euclidean lengths. Require recovered location and the correct acquisition forward residual, not an arbitrary image maximum.",
        ["Time grid not uniform/starting zero", "Non-surface source in this profile", "Image>1024 cells", "Even/zero wavelet"],
        ["Constant-background analytic rays only, no Devito/GPU/full-waveform velocity inversion.","Fixed internal LSQR callback captures real stop code, iterations and residual; image amplitude is not absolute impedance."])
    nt = 64
    impedance = [2e6*math.exp(.02*math.sin(2*math.pi*i/nt)) for i in range(nt)]
    post = [0.] + [.25*(math.log(impedance[i+1])-math.log(impedance[i-1])) for i in range(1,nt-1)] + [0.]
    add("GeoSeismicPoststackImpedanceInversion", "seismic_poststack_impedance_inversion", "pylops", "pylops.avo.poststack.PoststackInversion",
        "Recover absolute acoustic impedance conditional on a supplied positive background and known wavelet using the upstream log-impedance inverse operator.",
        {**solver_fields,**wav_fields,"poststack_trace":array(number(),16,512),"background_impedance_kg_m2_s":array(positive("Reference impedance kg/(m2*s).",1e3,1e10),16,512)},
        {"impedance_kg_m2_s":quantity("kg/(m2*s)",None),"residual":quantity("normalized amplitude",None)},
        dict(max_iterations=50,damping=.01,wavelet=[0,1,0],poststack_trace=post,background_impedance_kg_m2_s=[2e6]*nt),
        "seismic-imaging", "pylops/avo/poststack.py", "Estimates impedance from traces rather than computing SeismicReflectivity from given impedance.",
        "Independent delta-wavelet log-impedance derivative uses .5*d(log Z); constant known Z=2e6 produces zero trace and remains2e6 under the supplied prior. Add the nonconstant independently constructed sinusoidal log-impedance example; constant-only acceptance is insufficient.",
        ["No positive reference impedance", "Wavelet center/scale mismatch", "Unphysical recovered impedance"], ["Explicit half-factor in wavelet; upstream iteration count unavailable, actual forward/adjoint stationarity reported."])
    angles=[0,15,30]
    vp=[3000*math.exp(.02*math.sin(2*math.pi*i/nt)) for i in range(nt)]
    derivative=[0.]+[.5*(math.log(vp[i+1])-math.log(vp[i-1])) for i in range(1,nt-1)]+[0.]
    pre=[[.5*(1+math.tan(math.radians(a))**2)*v for a in angles] for v in derivative]
    add("GeoSeismicPrestackElasticInversion", "seismic_prestack_elastic_inversion", "pylops", "pylops.avo.prestack.PrestackInversion",
        "Jointly estimate Vp, Vs and density from angular seismic gathers with a fixed weak-contrast Aki-Richards inverse operator.",
        {**solver_fields,**wav_fields,"angle_gather_time_angle":array(array(number(),3,12),16,256),"angle_deg":array(number("Increasing incidence angle degrees.",0,35),3,12),"background_vp_vs_rho_si":matrix(3,256,positive("Vp m/s,Vs m/s,density kg/m3.",1,15000),16)},
        {"vp_vs_rho_si":quantity("m/s,m/s,kg/m3",None,3),"residual_gather":quantity("normalized amplitude",None,None)},
        dict(max_iterations=50,damping=.01,wavelet=[0,1,0],angle_gather_time_angle=pre,angle_deg=angles,background_vp_vs_rho_si=[[3000,1500,2200]]*nt),
        "seismic-imaging", "pylops/avo/prestack.py", "Joint angular elastic-property inversion differs from scalar poststack impedance inversion and accepted forward HTI/Zoeppritz operators.",
        "Independent linearized AVO coefficient for delta(log Vp)=.02 at normal incidence is .01 before the wavelet; at30deg coefficient is .5*(1+tan(30deg)^2)*.02=.01333333333333333. Recovery must report angular nonuniqueness, not exact unconstrained density truth.",
        ["Angular coverage<15deg", "Postcritical reference contrast", "Unstable elastic reference/result", "Log update>.25"], ["Upstream fixed Aki-Richards, no arbitrary linearization callable; no invented low-frequency properties."])
    pressure = [[(1. if i==10 else 0.)-(1. if i==18 else 0.) for i in range(64)] for _ in range(8)]
    pressure_fields={"pressure_receiver_time_pa":array(array(number("Calibrated acoustic pressure Pa."),32,512),8,32),"dt_s":dt,
                     "receiver_spacing_m":positive("Regular receiver spacing m.",.1,1000),"water_velocity_m_s":positive("Water speed m/s.",1000,2000)}
    add("GeoSeismicReceiverDeghosting", "seismic_receiver_deghosting", "pylops", "pylops.waveeqprocessing.Deghosting",
        "Recover upgoing/downgoing pressure using a fixed flat-receiver water-surface ghost operator and explicit direct-arrival pressure.",
        {**pressure_fields,**solver_fields,"direct_pressure_receiver_time_pa":array(array(number("Supplied direct-wave pressure Pa."),32,512),8,32),"receiver_depth_m":positive("Receiver depth below flat surface m.",.1,500)},
        {"upgoing_pressure_pa":quantity("Pa",None,None),"downgoing_pressure_pa":quantity("Pa",None,None)},
        dict(max_iterations=50,damping=.01,pressure_receiver_time_pa=pressure,direct_pressure_receiver_time_pa=[[0.]*64 for _ in range(8)],dt_s=.0025,receiver_spacing_m=10,water_velocity_m_s=1500,receiver_depth_m=15),
        "seismic-imaging", "pylops/waveeqprocessing/oneway.py", "Propagation ghost interference is not an instrument-response deconvolution or generic bandpass.",
        "Independent vertical-incidence receiver ghost delay2*z/v=.02s at z15m,v1500m/s, with opposite pressure polarity. A known unit upgoing pulse provides the deghosting amplitude reference outside notch ambiguity.",
        ["Shape mismatch", "Unknown direct arrival silently assumed", "Nonpositive depth/speed", "LSQR iteration/conditioning limit"], ["Fixed pressure kind, pad4,taper3; direct wave must be supplied, including explicit zeros if already removed. Real LSQR stop diagnostics retained."])
    p=[wave(64,4) for _ in range(8)]
    add("GeoSeismicUpDownWavefieldSeparation", "seismic_up_down_wavefield_separation", "pylops", "pylops.waveeqprocessing.WavefieldDecomposition",
        "Separate directional acoustic pressure wavefields using synchronized pressure and positive-down vertical particle velocity.",
        {**pressure_fields,"vertical_velocity_receiver_time_m_s":array(array(number("Positive-down calibrated particle velocity m/s."),32,512),8,32),"water_density_kg_m3":positive("Water density kg/m3.",900,1300)},
        {"upgoing_pressure_pa":quantity("Pa",None,None),"downgoing_pressure_pa":quantity("Pa",None,None)},
        dict(pressure_receiver_time_pa=p,vertical_velocity_receiver_time_m_s=[[v/(1000*1500) for v in row] for row in p],dt_s=.0025,receiver_spacing_m=10,water_velocity_m_s=1500,water_density_kg_m3=1000),
        "seismic-imaging", "pylops/waveeqprocessing/wavedecomposition.py", "Uses independent dual-sensor wavefields; single-component deghosting instead solves a water-surface propagation model.",
        "Independent normal-incidence downward wave obeys vz=p/(rho*c); pressure sinusoid of amplitude1Pa yields down amplitude1Pa and up0Pa. Add oblique mixed up/down waves and polarity reversal, not only vertical incidence.",
        ["Nonzero DC mean", "Velocity ENU-up mislabeled positive-down", "Different pressure/velocity sampling", "Evanescent components interpreted as recovered"], ["Fixed analytical decomposition, critical95%, taper3; no iterative solver or arbitrary transform."])
    kernel=[[[0.]*32 for _ in range(2)] for _ in range(2)]
    kernel[0][0][0]=100.; kernel[1][1][0]=100.
    add("GeoSeismicMultidimensionalDeconvolution", "seismic_multidimensional_deconvolution", "pylops", "pylops.waveeqprocessing.MDD; pylops.waveeqprocessing.MDC",
        "Recover a virtual-source pressure response from a calibrated multidimensional seismic convolution kernel with explicit temporal/spatial quadrature.",
        {**solver_fields,"kernel_source_receiver_time_per_m_s":tensor(8,8,256,min1=2,min2=2,min3=16),"data_source_time_pa":array(array(number("Source wavefield Pa."),16,256),2,8),
         "dt_s":dt,"receiver_spacing_m":positive("Receiver quadrature spacing m.",.1,1000)},
        {"virtual_source_response_pa":quantity("Pa",None,None),"time_s":quantity("s",None),"convolution_residual_pa":quantity("Pa",None,None)},
        dict(max_iterations=50,damping=.01,kernel_source_receiver_time_per_m_s=kernel,data_source_time_pa=[wave(32,2),wave(32,3)],dt_s=.01,receiver_spacing_m=1),
        "seismic-imaging", "pylops/waveeqprocessing/mdd.py", "Multi-receiver illumination deconvolution is not scalar instrument correction or Marchenko coupled focusing.",
        "Independent diagonal temporal-delta kernel with weight1/(dt*dr)=100 and dt.01,dr1 makes the convolution identity; damped inverse amplitudes scale by1/(1+damping^2). Add a cross-coupled independently constructed kernel and rank-deficiency case.",
        ["Zero kernel", "Wrong acquisition axes", "Unspecified kernel units", "Nonfinite stationarity/residual"], ["Kernel units fixed1/(m*s), wavefield Pa; two-sided response time origin explicit; LSQR count not exposed upstream, forward/adjoint stationarity reported."])


def dump(name, value):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
    FILES.append(name)


def write(name, text):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    FILES.append(name)


def registration(package):
    source = SOURCES[package]
    return dict(asset_version=source["version"], provider=source["repository"].split("/")[0], license=source["license"],
        license_scope="Pinned upstream dependency; adapter distribution-license review remains pending.", upstream_license=source["license"],
        source_url="https://github.com/"+source["repository"], source_commit=source["commit"], metadata_profile="scientific",
        official_protocol_version=None, official_protocol=dict(applicability="not_applicable",name=None,version=None),
        runtime=dict(python="3.12",dependency_lock=GROUP+"/requirements-"+package+".txt",environment_version="expansion501-geophysics-private-cpu-20261026",private_environment_required=True),
        lifecycle=dict(registration="candidate",contract_validation="not_run",unit_validation="not_run",workflow_validation="not_run",platform_validation="not_run",release_status="draft"),
        pending_fields=["cpu_acceptance","transitive_distribution_lock","adapter_license","receiving_lab_approval","private_worker_binding"],
        platform_validation="not_run",model_workflow_validation="not_run",deployment_status="not_deployed",submission_status="not_submitted",
        receiving_lab_approval="pending",formal_eligible=False)


def output_schema(row):
    digest = dict(type="string",pattern="^[0-9a-f]{64}$")
    provenance = obj({
        "tool":string(), "upstream_url":string(), "source_mode":string(), "reviewed_archive_commit":dict(type="string",pattern="^[0-9a-f]{40}$"),
        "installed_versions":dict(type="object",additionalProperties={"type":"string"}), "vendored_source":array(string(),0,32),
        "input_sha256":digest,"implementation_sha256":digest,"contract_sha256":digest,
        "output_sha256":dict(type="object",additionalProperties=digest),"network_required":{"type":"boolean","const":False},"runtime_source_correspondence":string()})
    diagnostics = obj({"method":string(),"convergence":string(),"iterations":nullable(integer("Reported iterations, null if upstream omits count.",0,10000)),
        "weighted_rms":nullable(number("Data RMS in supplied standard-deviation units.",0,1e200)),"residual_l2":nullable(number("Residual Euclidean norm.",0,1e200)),
        "stationarity_inf":nullable(number("Projected or normal-equation stationarity diagnostic.",0,1e200)),"warnings":array(string(),0,32),"uncertainty":string()})
    return obj({"values":obj({key:value["schema"] for key,value in row["outputs"].items()}),
        "units":obj({key:string("Unit: "+value["unit"]) for key,value in row["outputs"].items()}),
        "diagnostics":diagnostics,"artifacts":array(string("Shared-contract artifact path."),0,0),"provenance":provenance})


SKILLS = {
    "gravity-reference": ("Gravity reference reduction and density interpretation", "Begin with the declared coordinate/height datum and reference-density assumptions. Use normal gravity or slab/Airy calculations only for their stated physical models. Select tesseroid forward modelling or density inversion according to whether the property model is supplied or inferred; never subtract an unreviewed correction chain automatically."),
    "potential-interpretation": ("Potential-field continuation and source interpretation", "Distinguish field interpolation/continuation from ideal-source location and material-property inversion. Preserve spatial sampling, field/gradient units and magnetic directions. Compare diagnostic outputs and conditioning before interpreting any anomaly as a geological contact or body."),
    "electromagnetic": ("Controlled-source electrical and electromagnetic exploration", "Choose the observed physical quantity before choosing a model: DC voltage, IP apparent chargeability, complex secondary H, or transient dB/dt. Keep source geometry, background conductivity, current normalization and uncertainty explicit. Use forward reference problems before conditional bounded inversion; report every convergence limitation."),
    "waveform-quality": ("Calibrated waveform quality and event detection", "Establish response epoch, physical units, alignment and valid frequency support. Calibrate the waveform when a supported PZ response is available. Choose energy-window, template or phase-onset detection for the actual question; noise distributions and waveform misfits are evidence, not event probabilities."),
    "array-kinematics": ("Seismic array kinematics and waveform interpretation", "Confirm station/component axes and synchronized sampling. Select beamforming, polarization or small-strain inference according to available sensors. Reference rays and NMO do not infer a new Earth model. Interpret coherence, analytic attributes and radiation with their support masks and directional ambiguities."),
    "surface-waves": ("Layered surface-wave propagation and sensitivity", "Require a physically stable layered solid model with explicit halfspace. Start with mode existence and dispersion, then obtain modal displacement shapes or bundled layer sensitivities if needed. Never fill absent modes or interpret derivative kernels as posterior certainty."),
    "seismic-imaging": ("Bounded seismic imaging and elastic inversion", "Confirm geometry, wavelet normalization and the supplied low-frequency/background model. Use Kirchhoff LSM for reflectivity imaging, post/prestack inverse operators for conditional property estimation, and pressure/velocity wavefield operators for supported marine data. Inspect stop/residual/stationarity diagnostics before any interpretation."),
}


def main():
    records()
    tools, examples, candidates, statuses, plans = [], {}, [], [], []
    common_limits = ["source_revised_unverified; formal_eligible=false; acceptance_pending.",
        "No operation was executed in this authoring pass. NOT DEPLOYED / NOT SUBMITTED; workflow/model/platform validation not_run and receiving AI Lab approval pending.",
        "Only JSON scalar/array results; shared contracts add units validation, source/input hashes, provenance and artifacts=[]. No output_dir, runtime fetch, install, shell or user callable.",
        "Native/JIT imports require a parent-managed private CPU worker; no shared bridge/profile is modified. Preserve supplied baseline dependency pins."]
    for row in ROWS:
        source = SOURCES[row["package"]]
        requirements = list(dict.fromkeys([row["package"]+"=="+source["version"],*source["requirements"]]))
        interface = dict(status=STATUS,kind="expansion501_geophysics",path_fields=[],network_required=False,pure=False,
            validation="acceptance_pending",private_environment_required=True,
            entrypoint=dict(callable=MODULE+":"+row["function"],argument_parameter="args",bound_arguments={}))
        definition = {"type":"function","function":{"name":row["id"],"description":row["scientific_task"],"parameters":row["input_schema"]}}
        schema = output_schema(row)
        spec = dict(id=row["id"],name=row["id"],description=row["scientific_task"],when_to_use=row["scientific_task"],
            input_schema=row["input_schema"],output_schema=schema,result_schema=copy.deepcopy(schema),
            function=definition,function_definition=copy.deepcopy(definition),version="0.1.0",category="expansion501_geophysics",
            constraints=dict(finite_numbers_only=True,no_implicit_reprojection=True,no_automatic_dependency_install=True,max_json_bytes=4000000,max_array_elements=131072,cpu_only=True),
            metadata=dict(category="expansion501_geophysics",input_format="Strict JSON args object or JSON-object string; explicit units and synthetic/observed source declaration",output_format="Closed numeric JSON, shared provenance and empty artifact list",
                source="https://github.com/"+source["repository"],
                upstream=dict(package=row["package"],version=source["version"],license=source["license"],url="https://github.com/"+source["repository"],requirements=requirements,source_mode="package_release"),
                scientific_contract=dict(implementation_kind="upstream_library",review_status="acceptance_pending",formal_eligible=False,distinct_from_existing=row["distinct_from_existing"],numeric_oracle=row["numeric_oracle"])),
            source_interface=interface,example_arguments=row["example"],limitations=common_limits+row["limitations"],
            error_contract=dict(direct_exception="ScientificToolError",fields=["code","message","retryable"],codes=["invalid_arguments","missing_dependency","incompatible_dependency","resource_limit","unsupported_conditions","invalid_result","empty_input","upstream_failure"],retry_policy="Correct data/dependency/profile issues before retry; no blind scientific retry or invented successful result."),
            tags=["geophysics",row["package"],row["skill_group"]],registration_metadata=registration(row["package"]))
        tools.append(spec); examples[row["id"]]=row["example"]
        dump(ASSET+"/"+row["id"]+".json",row["example"])
        candidates.append(dict(tool_id=row["id"],capability_key="geophysics:"+row["function"].replace("_","-"),upstream_callable=row["upstream_callable"],
            scientific_task=row["scientific_task"],distinct_from_existing=row["distinct_from_existing"],numeric_oracle=row["numeric_oracle"],status=STATUS))
        statuses.append(dict(id=row["id"],state="source_adapted_unverified",reason="Concrete named decorated adapter and closed schemas authored; exact upstream pin recorded. Not executed or accepted; private CPU binding and scientific acceptance pending.",blockers=[]))
        plans.append(dict(id=row["id"],status="plan_only_not_executed",synthetic=True,oracle=row["numeric_oracle"],negative_constraints=row["negative_constraints"],
            receipt="No expected values were obtained by running an upstream kernel. Plans containing an unresolved absolute benchmark must be completed before scientific acceptance."))
    for tool_id,reason in BLOCKED.items():
        statuses.append(dict(id=tool_id,state="blocked",reason=reason,blockers=[reason]))
    skills=[]
    for key,(title,workflow) in SKILLS.items():
        rows=[r for r in ROWS if r["skill_group"]==key]
        ids=[r["id"] for r in rows]
        sid="expansion501-geophysics-"+key
        path="catalog/skills/"+sid+"/SKILL.md"
        meta=registration(rows[0]["package"])
        meta.update(provider="GeoAgent",license="Adapter distribution license pending; upstream licenses recorded per tool",pending_fields=["adapter_license","receiving_lab_approval","cpu_acceptance","workflow_acceptance"])
        skill=dict(id=sid,name=title,description=workflow,tool_references=ids,skill_file=path,
            metadata=dict(canonical_skill_file=path,validation="not_run",formal_eligible=False),
            delivery=dict(source_candidates=ids,unavailable_references=[],availability_status="source_candidates_authored_acceptance_pending",
                workflow_validation="not_run",model_workflow_validation="not_run",platform_validation="not_run",deployment_status="not_deployed",submission_status="not_submitted",receiving_lab_approval="pending"),
            registration_metadata=meta)
        skills.append(skill)
        front="---\nid: "+sid.replace("-","_")+"\nname: "+json.dumps(title)+"\ndescription: "+json.dumps(workflow)+"\nwhen_to_use: "+json.dumps(title+" with supplied measurements/models and explicit units")+"\ntools:\n"+"".join("- "+i+"\n" for i in ids)
        front+="required_inputs:\n- Strict tool JSON, explicit units, coordinate/component conventions and input_source\nconstraints:\n- No invented calibration, uncertainty, grade or reserves\n- Preserve physical assumptions, support masks and convergence diagnostics\n- Private CPU environment only, no GPU or runtime installation\nexpected_outputs:\n- Numeric JSON with units and shared provenance; artifacts is empty\n---\n"
        body="\n# "+title+"\n\n## When to use\n\n"+workflow+"\n\n## Required inputs\n\nEach tool has a closed schema. Field names encode physical units and ordered axes. All bundled examples are SYNTHETIC and unexecuted; they are not geological observations or passing receipts.\n\n## Workflow\n\n"+workflow+"\n\n## Tools and examples\n\n"
        for row in rows:
            body+="### "+row["id"]+"\n\n"+row["scientific_task"]+"\n\nExample: `"+ASSET+"/"+row["id"]+".json`. Limitations: "+" ".join(row["limitations"])+"\n\n"
        body+="## Source interface and delivery\n\nFixed named functions in `"+MODULE+"` accept `args` dict or JSON-object string through `collection_contracts.operation`. Parent stages the catalog and fixed module allowlist. No `output_dir` or file artifacts; shared contracts add input/source hashes, installed pins, provenance and `artifacts=[]`. No arbitrary shell, module, function, callback or dependency installation.\n\n## Expected outputs and interpretation\n\nRead `values`, `units` and `diagnostics` together. Null means explicitly unsupported/undefined support, not a measured zero. A returned model or zero residual is not proof of uniqueness or convergence. Report the actual upstream stop/independent stationarity result and conditional uncertainty.\n\n## Dependencies and licensing\n\nUse the exact per-package requirements in `"+GROUP+"/requirements-*.txt` in a private CPU environment, retaining baseline pins. Native wheel/build identity and the full transitive distribution lock remain parent acceptance prerequisites. ObsPy/PyLops LGPL terms and all other upstream licenses remain in force; adapter redistribution license review is pending.\n\n## Failure and handoff\n\nReturn native ScientificToolError failures, do not replace upstream kernels or silently fill missing physics. Parent owns scientific tests, shared dispatch/registry, transport approval and release. See adaptation-status.json for blocked assignments, which are not registered.\n\n## Validation and availability\n\nsource_revised_unverified; formal_eligible=false; acceptance_pending. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Availability: source_candidates_authored_acceptance_pending. Deployment status: not_deployed. Submission status: not_submitted. Workflow validation: not_run. Model workflow validation: not_run. Platform validation: not_run. Receiving AI Lab approval: pending. Internal schema conformance is NOT receiving AI Lab certification.\n"
        write(path,front+body)
    dump(GROUP+"/catalog-additions.json",dict(tools=tools,skills=skills))
    dump(GROUP+"/examples-additions.json",examples)
    dump(GROUP+"/candidate-operations.json",dict(group="geophysics",operations=candidates))
    dump(GROUP+"/adaptation-status.json",dict(operations=statuses))
    dump(GROUP+"/acceptance-plan.json",dict(status="plan_only_not_executed",operations=plans))
    evidence=[]
    for package,source in SOURCES.items():
        requirements=list(dict.fromkeys([package+"=="+source["version"],*source["requirements"]]))
        write(GROUP+"/requirements-"+package+".txt","# Private CPU direct/scientific contract pins, NOT an executed installation.\n# Parent must retain baseline and freeze remaining transitive distribution/build identities.\n"+"\n".join(requirements)+"\n")
        evidence.append({**source,"package":package,"source_url":"https://github.com/"+source["repository"]+"/tree/"+source["commit"],
            "license_evidence_url":"https://github.com/"+source["repository"]+"/blob/"+source["commit"]+"/"+source["license_file"],
            "published_release_evidence":"https://pypi.org/project/"+package+"/"+source["version"]+"/",
            "source_release_correspondence":"Reviewed source commit and published package pin are distinct evidence; parent must record wheel/build hashes before acceptance.",
            "review_status":"source_metadata_recorded_not_runtime_verified"})
    dump(GROUP+"/sources.json",dict(repositories=evidence,
        added_dependency_release_evidence=["https://pypi.org/project/"+p+"/"+v+"/" for p,v in [("discretize","0.12.0"),("pymatsolver","0.4.0"),("libdlf","0.3.0"),("scooby","0.10.2"),("verde","1.8.1"),("xrft","1.0.1")]],
        license_notes=["ObsPy and PyLops are LGPL, not silently relicensed as permissive.","Bruges transform/nmo.py additionally credits Leo Uieda under BSD-3-Clause.","Full transitive license/distribution review and adapter licensing pending; no AI Lab certification claimed."],
        entrypoints=[dict(id=r["id"],upstream_callable=r["upstream_callable"],source_url="https://github.com/"+SOURCES[r["package"]]["repository"]+"/blob/"+SOURCES[r["package"]]["commit"]+"/"+r["source_file"]) for r in ROWS]))
    dump(GROUP+"/private-cpu-policy.json",dict(status="design_only_binding_pending_parent",entry_module=MODULE,
        allowed_named_functions=[r["function"] for r in ROWS],transport="JSON only; no output_dir/artifacts; existing native_cpu_bridge profiles are NOT modified",
        python="3.12",gpu="forbidden",network_required=False,runtime_installation=False,private_workspace_required=True,
        cpu_threads=1,max_stdout_bytes=65536,max_stderr_bytes=65536,max_json_argument_bytes=4000000,max_result_bytes=16000000,
        memory_limit_mib=2048,deadline_seconds=120,exit_status="Parent fixed worker must preserve real exit code; timeout is not scientific success",
        cache_policy="Parent must route Numba/Matplotlib caches to the private workspace before import; no runtime modification of shared caches is authorized",
        identity="Package versions/source commits recorded; platform-specific wheel/native build hashes and approved executable identity pending parent receipt",
        artifact_transport="Not required by authored JSON-only functions. No claim of new raster/native artifact transport support."))
    write(ASSET+"/README.md","# Synthetic source-authoring inputs\n\nEvery JSON file is a synthetic, unexecuted input example. No file is a passing test receipt or evidence of real geological observations. Inversion examples may contain illustrative observations; independent absolute benchmarks are explicitly pending where noted in acceptance-plan.json.\n")
    write(GROUP+"/README.md","# Expansion501 geophysics source contribution\n\n42 concrete named adapters, 2 blocked assignments, 7 workflow Skills. Source revised and unverified, not usable/accepted by implication. No scientific calls, tests, installs, GPU, git, SSH, shared registry changes, deployment or model runs were executed.\n\nEntry contract: `"+MODULE+":<explicit_function>(args)` through `collection_contracts.operation`; kind `expansion501_geophysics`; no bound arguments, output_dir, runtime fetch or arbitrary dispatch. Output top-level is closed: values, units, diagnostics, artifacts, provenance. Parent must stage catalog and allowlist before decorated calls. All functions are pure=false conservatively due library/native/JIT caches and lifecycle uncertainty.\n\n`adaptation-status.json` covers all44 assignments exactly once by construction. `catalog-additions.json` includes only the42 authored functions; blocked Marchenko and traveltime tomography have no registered wrapper. `delivery-files.json` is the explicit repository-relative handoff. Requirements are exact direct/scientific contract pins, not a claim of a complete transitive wheel lock. Preserve SQLAlchemy1.4.54 and the supplied NumPy/SciPy/typing-extensions baseline. Parent controls private worker profiles and native identities.\n\nKnown pending scientific gates: independent absolute layered EM/inversion and iasp91 references; calibrated AR-pick false-positive/timing bounds; PPSD finite-window/bin references; layered modal displacement/sensitivity references; Fourier edge/critical-angle cases; all inversion residual, bound and convergence acceptance. These gaps are recorded, never labeled passed. Historical346/70 and all frozen/research materials remain untouched.\n\nNOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Workflow/model/platform validation not_run; receiving AI Lab approval pending. Internal schema metadata is not certification.\n")
    manifest=GROUP+"/delivery-files.json"
    dump(manifest,dict(files=FILES+[manifest]))
    print(json.dumps(dict(materialized_tools=len(tools),blocked=len(BLOCKED),skills=len(skills),delivery_manifest=manifest,status=STATUS)))


if __name__ == "__main__":
    main()
