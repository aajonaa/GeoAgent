"""Generate this group's additive SOURCE artifacts using only the standard library.

Does not import scientific packages, run tests, modify the registry, install,
access the network, commit, or deploy. Run from any directory with Python 3.12.
"""
import copy
import json
import math
import shutil
from pathlib import Path

GROUP = Path(__file__).resolve().parent
ROOT = GROUP.parents[4]
ASSET = "assets/github-expansion-geology"
DELIVERY = "catalog/source_delivery/github-expansion-20261025/groups/geology"
MODULE = "geological_agent.geology.github_expansion_geology"
SOURCE = "SYNTHETIC analytic acceptance fixture; not field observations or mineral evidence."
BASE = ["numpy==2.1.3", "scipy==1.15.3", "pandas==2.3.0", "matplotlib==3.10.7", "jsonschema==4.25.1"]
DEPS = {
    "apsg": ["apsg==2.0.6", "SQLAlchemy==1.4.54", "pygeomag==1.1.0"],
    "pyrolite": ["pyrolite==0.3.7", "periodictable==2.1.0", "mpltern==1.0.5", "sympy==1.14.0", "mpmath==1.3.0"],
    "scikit-gstat": ["scikit-gstat==1.0.24", "scikit-learn==1.7.2", "numba==0.68.0"],
    "gstools": ["gstools==1.7.0", "gstools-cython==1.2.0", "emcee==3.1.6", "hankel==1.2.2", "meshio==5.3.5", "pyevtk==1.7.0", "mpmath==1.3.0"],
    "lasio": ["lasio==0.32"],
    "welly": ["welly==0.5.2", "wellpathpy==0.5.2", "lasio==0.32", "striplog==0.9.2"],
    "striplog": ["striplog==0.9.2"],
    "scikit-learn": ["scikit-learn==1.7.2", "pyrolite==0.3.7", "periodictable==2.1.0", "mpltern==1.0.5", "sympy==1.14.0", "mpmath==1.3.0"],
}


BLOCKED_IDS = ("GeoAPSGBinghamAxialConfidence", "GeoPyroliteCIPWNorm")
WORKFLOWS = [
    [
        "github-geology-structural-fabrics",
        "Structural fabrics and field inference",
        [
            "GeoAPSGPairFabricTensor",
            "GeoAPSGFoldAxis",
            "GeoAPSGFisherDirectionalConfidence",
            "GeoAPSGMarkerStrainEstimate",
            "GeoAPSGFaultKinematicAxes"
        ]
    ],
    [
        "github-geology-strain-stress",
        "Finite strain, flow and fracture stress",
        [
            "GeoAPSGFiniteStrainEllipsoid",
            "GeoAPSGDeformationPolarSplit",
            "GeoAPSGVelocityGradientEvolution",
            "GeoAPSGKinematicVorticity",
            "GeoAPSGFractureTraction",
            "GeoAPSGFaultReactivation"
        ]
    ],
    [
        "github-geology-mineral-chemistry",
        "Compositional and endmember mineral chemistry",
        [
            "GeoPyroliteALR",
            "GeoPyroliteILR",
            "GeoPyroliteCompositionalCenter",
            "GeoPyroliteSphericalComposition",
            "GeoPyroliteMineralEndmemberUnmix"
        ]
    ],
    [
        "github-geology-geostat-validation",
        "Geostatistical models and background validation",
        [
            "GeoSKGstatRobustVariogram",
            "GeoSKGstatSpaceTimeVariogram",
            "GeoGSToolsVariogramFit",
            "GeoGSToolsBlockSupportCovariance",
            "GeoSKGstatKrigingLOO",
            "GeoGeochemBackgroundDistance"
        ]
    ],
    [
        "github-geology-drillhole-logs",
        "Drillhole survey and interval-log analysis",
        [
            "GeoLasioLogAudit",
            "GeoWellyMinimumCurvature",
            "GeoWellyLogResample",
            "GeoWellyLogDespike",
            "GeoWellyLogFaciesBlock",
            "GeoStriplogIntervalIntersection"
        ]
    ]
]
SNAPSHOT = GROUP / "revisions/r1-source-snapshot"


def preserve_previous_generated_sources():
    """Preserve pre-r2 generated sources once; never overwrite historical evidence."""
    group_files = [
        "catalog-additions.json", "candidate-operations.json", "examples-additions.json",
        "oracle-cases.json", "requirements.txt", "delivery-status.json",
    ]
    paths = [GROUP / name for name in group_files]
    paths += [ROOT / "catalog/skills" / key / "SKILL.md" for key, _, _ in WORKFLOWS]
    active_ids = [name for _, _, names in WORKFLOWS for name in names]
    paths += [ROOT / ASSET / (name + ".json") for name in active_ids + list(BLOCKED_IDS)]
    paths += [ROOT / ASSET / name for name in ("README.md", "synthetic-log.las", "synthetic-nonmonotone.las")]
    for source in paths:
        target = SNAPSHOT / source.relative_to(ROOT)
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    # Only these two known, archived argument files are retired from the active set.
    for name in BLOCKED_IDS:
        source = ROOT / ASSET / (name + ".json")
        archived = SNAPSHOT / source.relative_to(ROOT)
        if source.is_file():
            if source.resolve().parent != (ROOT / ASSET).resolve() or not archived.is_file():
                raise RuntimeError("Refusing to retire an unarchived or out-of-scope example")
            source.unlink()


def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": False}


def num(description, **limits):
    return {"type": "number", "description": description, **limits}


def integer(description, minimum=0, maximum=10000):
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def string(description, **limits):
    return {"type": "string", "description": description, "minLength": 1, "maxLength": 512, **limits}


def array(description, items=None, minimum=1, maximum=256):
    return {"type": "array", "description": description, "items": items or num("Finite numeric value."), "minItems": minimum, "maxItems": maximum}


def matrix(description, columns=None, minimum=1, maximum=256, positive=False, nullable=False):
    cell = num("Finite value.", minimum=1e-12, maximum=1e12) if positive else num("Finite value.", minimum=-1e12, maximum=1e12)
    if nullable:
        cell = {"type": ["number", "null"]}
    row = array("One aligned row.", cell, minimum=columns or 1, maximum=columns or 128)
    return array(description, row, minimum=minimum, maximum=maximum)


def labels(description, minimum=1, maximum=128):
    value = array(description, string("Explicit measured-data label.", maxLength=80), minimum, maximum)
    value["uniqueItems"] = True
    return value


def tensor(description, dimension=3):
    return matrix(description, dimension, dimension, dimension)


NED = {"coordinate_frame": {"const": "NED", "type": "string", "description": "Right-handed north, east, down frame; vectors are not longitude/latitude."}}
UNITS = string("One explicit unit shared by all values; no implicit conversion.", enum=["ppm", "wt_percent", "dimensionless"])
GAMMA_UNITS = ["ppm^2", "wt_percent^2", "dimensionless^2"]
CHEM = {"components": labels("Chemical components in the exact numeric-column order.", 2, 12),
        "values": matrix("Strictly positive compositions; zeros and censored values are not imputed.", maximum=128, positive=True),
        "input_unit": string("Common input concentration unit.", enum=["ppm", "wt_percent", "mass_fraction"])}
LOG = {"depth_m": array("Measured depths in metres, increasing; no missing values.", num("Depth in m.", minimum=0, maximum=1e7), 2, 10000),
       "values": array("Measured log values aligned to depth.", num("Value in the explicit shared unit.", minimum=-1e12, maximum=1e12), 2, 10000),
       "value_unit": UNITS}
SPATIAL = {"coordinates_m": matrix("Unique local projected x,y locations in metres, never latitude/longitude.", 2, 4, 256),
           "values": array("Aligned measured concentrations or properties.", num("Value in declared units.", minimum=-1e12, maximum=1e12), 4, 256),
           "value_unit": UNITS}
NULLNUM = {"type": ["number", "null"], "description": "Null only when the documented statistic is undefined or bin is empty."}


def check(path, expected, atol=1e-8, rtol=1e-6, absolute=False):
    return {"path": path.split("/"), "expected": expected, "atol": atol, "rtol": rtol, "absolute": absolute}


def records():
    rows = []
    def add(tool_id, function, package, task, upstream, api_path, inputs, outputs, units, args,
            negative, oracle, checks, distinct, limitation, negative_code="invalid_arguments", paths=None):
        args = {"data_source": SOURCE, **args}
        bad = copy.deepcopy(args)
        bad.update(negative)
        rows.append(dict(tool_id=tool_id, function=function, package=package, scientific_task=task,
                         upstream_callable=upstream, api_path=api_path,
                         input_schema=obj({"data_source": string("Caller-declared measurement/reference provenance; not independently authenticated.", minLength=8), **inputs}),
                         outputs=outputs, units=units, arguments=args, negative_arguments=bad,
                         negative_code=negative_code, numeric_oracle=oracle, checks=checks,
                         distinct_from_existing=distinct, limitation=limitation, path_fields=paths or []))
    vec = matrix("Nonzero measured vectors, normalized by the upstream kernel.", 3, 1, 256)
    pairs = {**NED, "normal_vectors": vec, "line_vectors": vec}
    tensor3 = "src/apsg/feature/_tensor3.py"
    container = "src/apsg/feature/_container.py"
    codata = "pyrolite/comp/codata.py"
    normative = "pyrolite/mineral/normative.py"
    n = [[0, 0, 1]] * 4
    l = [[1, 0, 0]] * 4
    add("GeoAPSGPairFabricTensor", "paired_fabric_tensor", "apsg", "Estimate Lisle joint foliation-lineation fabric from orthogonal measured pairs.",
        "apsg.feature.OrientationTensor3.from_pairs", tensor3, pairs,
        {"tensor": tensor("Shifted Lisle tensor (L-P+I)/3."), "eigenvalues": array("Descending tensor eigenvalues.", minimum=3, maximum=3)},
        {"tensor": "1", "eigenvalues": "1"}, {"coordinate_frame": "NED", "normal_vectors": n, "line_vectors": l},
        {"line_vectors": [[0, 0, 1]] * 4},
        "Identical horizontal planes with north-directed in-plane lines give diag(2/3,1/3,0), independently from averages of dyads.",
        [check("tensor", [[2/3, 0, 0], [0, 1/3, 0], [0, 0, 0]]), check("eigenvalues", [2/3, 1/3, 0])],
        "GeoStereonetAnalysis uses plane poles alone; Lisle fabric uses jointly observed lineations and planes, so different lineation fabrics remain distinguishable.",
        "Vectors must be orthogonal within 1e-8 cosine. No automatic adjustment of field measurements. The shifted tensor is a fabric descriptor, not strain magnitude.")
    fold_normals = [[1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]]
    add("GeoAPSGFoldAxis", "cylindrical_fold_axis", "apsg", "Estimate the unique cylindrical-fold axis from the girdle of measured plane poles.",
        "apsg.feature.OrientationTensor3.from_features", tensor3,
        {**NED, "normal_vectors": matrix("Bedding-plane normals; antipodes are equivalent.", 3, 4, 256)},
        {"axis_ned": array("Unoriented least-eigenvalue axis; sign has no geological meaning.", minimum=3, maximum=3), "eigenvalues": array("Descending pole moment eigenvalues.", minimum=3, maximum=3), "girdle_gap": num("Second minus third eigenvalue; uniqueness diagnostic.")},
        {"axis_ned": "1", "eigenvalues": "1", "girdle_gap": "1"}, {"coordinate_frame": "NED", "normal_vectors": fold_normals},
        {"normal_vectors": [[1, 0, 0]] * 4},
        "Poles +/-north and +/-east have moment diag(1/2,1/2,0); fold axis is vertical up to sign and eigenvalue gap is 1/2.",
        [check("axis_ned/2", 1, absolute=True), check("girdle_gap", .5), check("eigenvalues", [.5, .5, 0])],
        "GeoStereonetAnalysis fits a dominant plane using its leading pole eigenvector. A cylindrical fold uses the least-eigenvalue girdle axis, a different geological inference.",
        "Assumes approximately cylindrical folding. A unique mathematical axis is not evidence that the outcrop satisfies this geological assumption.", "unsupported_conditions")
    direction = [[math.sqrt(3)/2, .5, 0], [math.sqrt(3)/2, -.5, 0]] * 2
    alpha = math.degrees(math.acos(1 - (1-math.sqrt(3)/2)/(math.sqrt(3)/2) * (.05**(-1/3)-1)))
    add("GeoAPSGFisherDirectionalConfidence", "fisher_directional_confidence", "apsg", "Estimate a Fisher population mean and confidence cone for directed structural measurements.",
        "apsg.feature.Vector3Set.fisher_statistics", container,
        {**NED, "directed_vectors": matrix("Directed observations, NOT unoriented axial lineations.", 3, 4, 256), "confidence_level": num("Confidence probability.", minimum=.5, maximum=.99)},
        {"mean_direction_ned": array("Directed mean unit vector.", minimum=3, maximum=3), "precision": num("Fisher concentration kappa."), "confidence_half_angle": num("Confidence-cone half-angle in degrees."), "resultant_length_per_sample": num("Mean resultant length.")},
        {"mean_direction_ned": "1", "precision": "1", "confidence_half_angle": "degree", "resultant_length_per_sample": "1"},
        {"coordinate_frame": "NED", "directed_vectors": direction, "confidence_level": .95},
        {"directed_vectors": [[1, 0, 0]] * 4},
        "Four directed vectors at +/-30 degrees from north have R/N=sqrt(3)/2. Fisher cone follows acos(1-(N-R)/R*(0.05^(-1/(N-1))-1)); kappa additionally obeys coth(k)-1/k=R/N.",
        [check("mean_direction_ned", [1, 0, 0]), check("resultant_length_per_sample", math.sqrt(3)/2), check("confidence_half_angle", alpha)],
        "Existing stereonet and plane-intersection tools have no directional population confidence calculation. Directed polarity is retained rather than folded to an axial hemisphere.",
        "Independent Fisher-distributed directed measurements are assumed. Rejects zero resultant and perfect alignment, where this release gives undefined or infinite statistics.", "unsupported_conditions")
    add("GeoAPSGMarkerStrainEstimate", "marker_strain_estimate", "apsg", "Infer planar strain from measured elliptical markers using Rf/phi, with Robin log-tensor comparison.",
        "apsg.feature.EllipseSet.rfphi", container,
        {"marker_tensors": array("Measured squared-axis ellipse tensors in one shared 2D section frame.", tensor("Symmetric positive-definite ellipse tensor.", 2), 3, 128), "section_frame": string("Caller-declared fixed section axes; not inferred.")},
        {"rfphi_axial_ratio": num("Rf/phi estimated axial ratio."), "rfphi_orientation": num("Orientation modulo 180 degrees in section coordinates."), "robin_axial_ratio": num("Robin tensor-mean axial ratio."), "robin_orientation": num("Robin orientation modulo 180 degrees.")},
        {"rfphi_axial_ratio":"1","rfphi_orientation":"degree","robin_axial_ratio":"1","robin_orientation":"degree"},
        {"marker_tensors": [[[4,0],[0,1]]]*3, "section_frame": "SYNTHETIC x=north,y=east planar section"},
        {"marker_tensors": [[[1,2],[2,1]]]*3},
        "Identical ellipses with semiaxes 2 and 1 along the section axes have Rf/phi ratio 2 and Robin ratio 2, both at zero degrees.",
        [check("rfphi_axial_ratio",2),check("robin_axial_ratio",2),check("rfphi_orientation",0)],
        "No baseline operation estimates finite strain from elliptical grain/marker populations; pole stereonets cannot infer marker axial ratios.",
        "Strain interpretation assumes suitable passive markers and an initially unpreferred population; Rf/phi and Robin are reported together as one task, not counted as separate methods.")
    add("GeoAPSGFaultKinematicAxes", "fault_kinematic_axes", "apsg", "Derive fault-slip kinematic compression/extension bisector axes from measured plane and directed slip pairs.",
        "apsg.feature.Fault.p_vector", "src/apsg/feature/_geodata.py", pairs,
        {"p_axes_ned": matrix("Kinematic P axes; signs are not oriented stress directions.",3), "t_axes_ned": matrix("Kinematic T axes.",3)},
        {"p_axes_ned":"1","t_axes_ned":"1"}, {"coordinate_frame":"NED","normal_vectors":[[0,0,1]],"line_vectors":[[1,0,0]]},
        {"line_vectors":[[0,0,1]]},
        "A down normal and north slip have bisectors with north and down absolute components 1/sqrt(2), with P and T mutually orthogonal.",
        [check("p_axes_ned/0/0",1/math.sqrt(2),absolute=True),check("t_axes_ned/0/2",1/math.sqrt(2),absolute=True)],
        "GeoStructuralPlaneIntersection intersects two planes. This operation uses a measured slip direction and one fault plane to derive kinematic P/T axes, without stress inversion.",
        "Normal and slip are supplied as an oriented compatible pair. P/T axes are kinematic bisectors and do not determine stress magnitudes or a unique regional paleostress.")
    finite_input={**NED,"deformation_gradient":tensor("Dimensionless deformation gradient in NED coordinates.")}
    add("GeoAPSGFiniteStrainEllipsoid","finite_strain_ellipsoid","apsg","Recover principal stretches, Hencky strains and Flinn shape from a measured finite deformation gradient.",
        "apsg.feature.Ellipsoid.from_defgrad",tensor3,finite_input,
        {"left_cauchy_green":tensor("Left finite-strain tensor F F^T."),"principal_stretches":array("Descending principal stretches.",minimum=3,maximum=3),"hencky_strains":array("Natural logarithms of stretches.",minimum=3,maximum=3),"flinn_k":NULLNUM,"volume_ratio":num("Determinant of deformation gradient.")},
        {"left_cauchy_green":"1","principal_stretches":"1","hencky_strains":"1","flinn_k":"1","volume_ratio":"1"},
        {"coordinate_frame":"NED","deformation_gradient":[[2,0,0],[0,1,0],[0,0,.5]]},
        {"deformation_gradient":[[-2,0,0],[0,1,0],[0,0,.5]]},
        "Isochoric diagonal stretch (2,1,1/2) yields tensor diag(4,1,1/4), stretches 2,1,1/2, log-strains +/-ln2 and Flinn k=1.",
        [check("principal_stretches",[2,1,.5]),check("hencky_strains",[math.log(2),0,-math.log(2)]),check("flinn_k",1),check("volume_ratio",1)],
        "Baseline structural operations address plane geometry, not finite deformation tensors or strain-ellipsoid shape.",
        "The deformation gradient must be externally measured/derived. No inversion from orientation alone; singular/reflection gradients rejected. Flinn k is null where its denominator vanishes.")
    add("GeoAPSGDeformationPolarSplit","deformation_polar_split","apsg","Separate rigid rotation from finite material stretch in a structural deformation gradient.",
        "apsg.feature.DeformationGradient3",tensor3,finite_input,
        {"rotation":tensor("Proper orthogonal polar rotation."),"right_stretch":tensor("Material-coordinate right stretch."),"left_stretch":tensor("Spatial-coordinate left stretch."),"rotation_angle":num("Absolute polar rotation angle in degrees.")},
        {"rotation":"1","right_stretch":"1","left_stretch":"1","rotation_angle":"degree"},
        {"coordinate_frame":"NED","deformation_gradient":[[0,-1,0],[2,0,0],[0,0,.5]]},
        {"deformation_gradient":[[0,0,0],[0,1,0],[0,0,1]]},
        "A 90-degree vertical-axis rotation times diag(2,1,1/2) has right stretch diag(2,1,1/2), left stretch diag(1,2,1/2), and rotation angle 90 degrees.",
        [check("right_stretch",[[2,0,0],[0,1,0],[0,0,.5]]),check("left_stretch",[[1,0,0],[0,2,0],[0,0,.5]]),check("rotation_angle",90)],
        "Finite-strain eigenvalues describe stretching but do not recover rigid-body rotation. No baseline stereonet tool performs deformation polar decomposition.",
        "Polar rotation describes the supplied finite mapping, not the entire tectonic rotation history; requires a nonsingular orientation-preserving gradient.")
    velocity={**NED,"velocity_gradient_per_myr":tensor("Constant spatial velocity gradient, Myr^-1.")}
    simple=[[0,1,0],[0,0,0],[0,0,0]]
    add("GeoAPSGVelocityGradientEvolution","velocity_gradient_evolution","apsg","Integrate a constant tectonic velocity gradient over an explicit duration using the upstream matrix exponential.",
        "apsg.feature.VelocityGradient3.defgrad",tensor3,{**velocity,"duration_myr":num("Duration in Myr.",exclusiveMinimum=0,maximum=1000)},
        {"deformation_gradient":tensor("Accumulated finite deformation."),"volume_ratio":num("Accumulated volume ratio."),"duration_myr":num("Applied duration.")},
        {"deformation_gradient":"1","volume_ratio":"1","duration_myr":"Myr"},
        {"coordinate_frame":"NED","velocity_gradient_per_myr":simple,"duration_myr":2},
        {"duration_myr":100},
        "Unit simple shear has L^2=0, hence exp(2L)=I+2L; F_xy=2 and determinant=1 independently of numerical exponentiation.",
        [check("deformation_gradient",[[1,2,0],[0,1,0],[0,0,1]]),check("volume_ratio",1)],
        "Static plane or finite-strain analysis does not integrate a time-dependent deformation mapping. This tool solves the constant-flow evolution task.",
        "Constant homogeneous velocity gradient is assumed; variable tectonic histories are unsupported. Frobenius norm times duration is bounded by 20.")
    add("GeoAPSGKinematicVorticity","kinematic_vorticity","apsg","Quantify noncoaxial deformation through strain rate, spin and the kinematic vorticity number.",
        "apsg.feature.VelocityGradient3",tensor3,velocity,
        {"kinematic_vorticity":num("Spin-to-strain-rate norm ratio."),"vorticity_magnitude":num("Curl magnitude in Myr^-1."),"strain_rate":tensor("Symmetric rate tensor."),"spin":tensor("Antisymmetric spin tensor.")},
        {"kinematic_vorticity":"1","vorticity_magnitude":"Myr^-1","strain_rate":"Myr^-1","spin":"Myr^-1"},
        {"coordinate_frame":"NED","velocity_gradient_per_myr":simple},
        {"velocity_gradient_per_myr":[[0,-1,0],[1,0,0],[0,0,0]]},
        "Unit simple shear has symmetric and antisymmetric xy components 1/2, equal tensor norms, Wk=1 and curl magnitude 1/Myr.",
        [check("kinematic_vorticity",1),check("vorticity_magnitude",1),check("strain_rate/0/1",.5)],
        "Finite polar rotation is an accumulated mapping property; kinematic vorticity diagnoses instantaneous coaxial versus noncoaxial flow and is not a duplicate rotation calculation.",
        "Requires nonzero symmetric strain rate. Pure rigid rotation has infinite Wk and is explicitly rejected rather than clipped.","unsupported_conditions")
    stress={**NED,"stress_mpa":tensor("Symmetric compression-positive total stress in MPa."),"normal_vectors":vec}
    stress_args={"coordinate_frame":"NED","stress_mpa":[[100,0,0],[0,60,0],[0,0,20]],"normal_vectors":[[1,0,1]]}
    add("GeoAPSGFractureTraction","fracture_traction","apsg","Resolve measured stress onto fracture planes, retaining normal compression, shear magnitude and physical traction.",
        "apsg.feature.Stress3.stress_comp",tensor3,stress,
        {"normal_compression":array("Compression-positive resolved normal stress."),"shear_magnitude":array("Nonnegative resolved shear magnitude."),"physical_traction_ned":matrix("Physical tension-positive traction vector sigma_mechanical*n.",3)},
        {"normal_compression":"MPa","shear_magnitude":"MPa","physical_traction_ned":"MPa"},stress_args,
        {"stress_mpa":[[100,1,0],[0,60,0],[0,0,20]]},
        "For diag(100,60,20) MPa and a 45-degree north/down normal, resolved compression is (100+20)/2=60 MPa and shear is (100-20)/2=40 MPa.",
        [check("normal_compression/0",60),check("shear_magnitude/0",40)],
        "No baseline tool projects a geological stress tensor onto fractures. This returns traction, whereas plane intersections return only geometric lines.",
        "APSG must already use its default geological compression-positive convention. Physical traction vectors remain tension-positive; the adapter never changes process-global settings.")
    add("GeoAPSGFaultReactivation","fault_reactivation","apsg","Assess frictional reactivation of closed fractures under declared pore pressure and Mohr-Coulomb parameters.",
        "apsg.feature.Stress3.slip_tendency",tensor3,
        {**stress,"pore_pressure_mpa":num("Isotropic pore pressure; Terzaghi coefficient one.",minimum=0,maximum=1e5),"friction_coefficient":num("Explicit laboratory/scenario friction coefficient.",exclusiveMinimum=0,maximum=2),"cohesion_mpa":num("Explicit cohesion.",minimum=0,maximum=1e5)},
        {"effective_normal_compression":array("Normal compression after pressure reduction."),"slip_tendency":array("Shear divided by effective normal compression."),"dilation_tendency":array("Normalized dilation tendency."),"coulomb_excess":array("Shear minus cohesion minus friction*effective normal; positive exceeds declared criterion.")},
        {"effective_normal_compression":"MPa","slip_tendency":"1","dilation_tendency":"1","coulomb_excess":"MPa"},
        {**stress_args,"pore_pressure_mpa":10,"friction_coefficient":.6,"cohesion_mpa":0},
        {"pore_pressure_mpa":60},
        "The 60 MPa normal/40 MPa shear fixture at 10 MPa pore pressure has effective normal 50, slip tendency .8, dilation .5, and Coulomb excess 40-.6*50=10 MPa.",
        [check("effective_normal_compression/0",50),check("slip_tendency/0",.8),check("dilation_tendency/0",.5),check("coulomb_excess/0",10)],
        "Traction alone contains no pore-pressure/friction failure criterion. This task explicitly evaluates closed-fracture reactivation, without elastic or seismic modeling.",
        "Assumes isotropic pressure, Biot/Terzaghi coefficient one and a closed frictional plane. Rejects hydrostatic stress and tensile/open-fracture cases; not a site-specific stability certification.","unsupported_conditions")
    chem_args={"components":["Cu","Pb","Zn"],"values":[[2,4,1]],"input_unit":"ppm"}
    add("GeoPyroliteALR","additive_logratio","pyrolite","Express positive geochemical compositions as additive log ratios to an explicitly selected reference component.",
        "pyrolite.comp.codata.ALR",codata,{**CHEM,"denominator":string("Exact reference component name.",maxLength=80)},
        {"components":labels("Original component order."),"denominator":string("Chosen reference component."),"alr":matrix("Natural log of each non-reference component/reference."),"closed_compositions":matrix("Upstream inverse ALR closed to one.")},
        {"alr":"ln_ratio","closed_compositions":"fraction"},{**chem_args,"denominator":"Zn"},
        {"denominator":"ABSENT"},
        "For [2,4,1] with third-component reference, coordinates are [ln2,ln4] and inverse closure gives [2/7,4/7,1/7].",
        [check("alr",[[math.log(2),math.log(4)]]),check("closed_compositions",[[2/7,4/7,1/7]])],
        "GeoGeochemCLR uses the geometric mean and D redundant coordinates. ALR uses a declared analyte reference and D-1 coordinates with a distinct interpretive meaning.",
        "Reference choice matters. All components must be positive and share one concentration unit; censored/zero data require an independently justified treatment outside this tool.")
    basis=[[1/math.sqrt(2),-1/math.sqrt(2),0],[1/math.sqrt(6),1/math.sqrt(6),-2/math.sqrt(6)]]
    add("GeoPyroliteILR","isometric_logratio","pyrolite","Map chemical compositions into explicitly defined orthonormal log-ratio balances for valid Euclidean analysis.",
        "pyrolite.comp.codata.ILR",codata,{**CHEM,"basis":matrix("D-1 by D orthonormal contrast matrix; rows sum to zero.",maximum=11)},
        {"components":labels("Original components."),"ilr":matrix("D-1 isometric coordinates."),"basis":matrix("Applied basis."),"closed_compositions":matrix("Upstream inverse ILR closed to one.")},
        {"ilr":"orthonormal_ln_ratio","closed_compositions":"fraction","basis":"1"},
        {**chem_args,"values":[[4,2,1]],"basis":basis}, {"basis":[[1,0,0],[0,1,0]]},
        "For [4,2,1] and the stated Helmert contrasts, balances are ln2/sqrt2 and 3ln2/sqrt6; reconstructed fractions are 4/7,2/7,1/7.",
        [check("ilr",[[math.log(2)/math.sqrt(2),3*math.log(2)/math.sqrt(6)]]),check("closed_compositions",[[4/7,2/7,1/7]])],
        "GeoGeochemCLR is rank-deficient in D-dimensional Euclidean space. ILR supplies a complete orthonormal D-1 basis, not an alias of CLR output.",
        "The scientifically appropriate balance basis is supplied by the caller. The adapter checks orthonormality and zero-sum contrasts and does not invent element groups.")
    add("GeoPyroliteCompositionalCenter","compositional_center","pyrolite","Estimate the Aitchison center of a population of positive geological compositions.",
        "pyrolite.comp.codata.logratiomean",codata,CHEM,
        {"components":labels("Original components."),"center":array("Closed component-wise geometric mean.")},{"center":"fraction"},
        {"components":["Cu","Zn"],"values":[[1,4],[4,1]],"input_unit":"ppm"}, {"values":[[1,4]]},
        "Geometric component means of [1,4] and [4,1] are both 2; closure gives [.5,.5], unlike an absolute concentration estimate.",
        [check("center",[.5,.5])],
        "GeoGeochemCLR transforms individual rows; it does not estimate a sample population center in the simplex.",
        "Equal sample weights are assumed. The center describes relative composition, not mean assay grade or mass-weighted material composition.")
    add("GeoPyroliteSphericalComposition","spherical_composition","pyrolite","Represent closed mineral-chemical compositions as positive-orthant spherical angles and reconstruct their fractions.",
        "pyrolite.comp.codata.sphere",codata,CHEM,
        {"components":labels("Component order determines angular convention."),"angles":matrix("Upstream sphere angular coordinates in radians."),"closed_compositions":matrix("Reconstructed closed fractions.")},
        {"angles":"radian","closed_compositions":"fraction"}, {**chem_args,"values":[[1,1,2]]}, {"values":[[0,1,2]]},
        "Closure of [1,1,2] gives [1/4,1/4,1/2]; square-root coordinates [.5,.5,1/sqrt2] yield both upstream ordered angles pi/4.",
        [check("angles",[[math.pi/4,math.pi/4]]),check("closed_compositions",[[.25,.25,.5]])],
        "This square-root simplex/sphere representation is neither CLR/ALR/ILR log-ratio geometry nor the existing stereonet mapping of geological directions.",
        "Angular results depend on component order and are not geographic bearings or an Aitchison distance. Positive inputs only; no zero replacement.")
    add("GeoPyroliteMineralEndmemberUnmix","mineral_endmember_unmix","pyrolite","Fit supplied chemical compositions to an explicit independent mineral endmember mass-fraction model.",
        "pyrolite.mineral.normative.unmix",normative,
        {"components":labels("Aligned chemical mass-fraction components.",2,16),"compositions":matrix("Complete closed nonnegative input mass fractions.",maximum=16),"endmembers":matrix("Complete closed endmember mass fractions.",minimum=2,maximum=16),"endmember_labels":labels("Caller-supplied mineral model labels.",2,16),"input_unit":{"type":"string","const":"mass_fraction"},"maximum_rmse":num("Maximum accepted reconstruction residual in mass fraction.",minimum=1e-6,maximum=.05)},
        {"endmember_labels":labels("Supplied labels, not identified minerals."),"weights":matrix("Nonnegative endmember model coefficients."),"reconstructed":matrix("Chemical reconstruction."),"rmse":array("Per-sample chemical residual.")},
        {"weights":"endmember_model_fraction","reconstructed":"mass_fraction","rmse":"mass_fraction"},
        {"components":["A","B"],"compositions":[[.25,.75]],"endmembers":[[1,0],[0,1]],"endmember_labels":["SYNTHETIC_A","SYNTHETIC_B"],"input_unit":"mass_fraction","maximum_rmse":.001},
        {"endmembers":[[1,0],[1,0]]},
        "Two orthogonal closed endmembers make the uniquely feasible mixture of [.25,.75] exactly [.25,.75]; this is an analytic mass-balance oracle, not a second optimizer.",
        [check("weights",[[.25,.75]],atol=3e-5),check("reconstructed",[[.25,.75]],atol=3e-5)],
        "GeoSpectralLinearUnmix fits unconstrained reflectance coefficients. This fits nonnegative closed chemical mass-fraction endmembers, with different physical inputs and constraints.",
        "One sample is passed to upstream unmix at a time because its multi-row closure constraint is global. Solver success is not exposed upstream; returned fits must pass explicit residual bounds. Coefficients do not establish ore grade or verified mineral modes.","unsupported_conditions")
    spatial_args={"coordinates_m":[[0,0],[1,0],[2,0],[3,0]],"values":[0,2,4,6],"value_unit":"ppm"}
    add("GeoSKGstatRobustVariogram","robust_variogram_comparison","scikit-gstat","Compare classical, Cressie-Hawkins and Dowd empirical semivariograms on the same geological sample pairs.",
        "skgstat.estimators.cressie","skgstat/estimators.py",
        {**SPATIAL,"lag_upper_edges_m":array("Positive increasing upper edges; [lower,upper) convention.",num("Lag upper edge in m.",exclusiveMinimum=0,maximum=1e9),1,32)},
        {"lag_upper_edges_m":array("Actual bin upper edges."),"pair_counts":array("Number of contributing unordered pairs.",integer("Pair count.",0,32640)),"matheron":array("Classical semivariance; null for empty bin.",NULLNUM),"cressie_hawkins":array("Robust semivariance; null for empty bin.",NULLNUM),"dowd":array("Median-based semivariance; null for empty bin.",NULLNUM)},
        {"lag_upper_edges_m":"m","matheron":GAMMA_UNITS,"cressie_hawkins":GAMMA_UNITS,"dowd":GAMMA_UNITS,"pair_counts":"count"},
        {**spatial_args,"lag_upper_edges_m":[1.5,2.5,3.5]}, {"lag_upper_edges_m":[2,1]},
        "For a concentration ramp of 2 ppm/m, lag differences are 2,4,6 and counts 3,2,1. Matheron is [2,8,18]; first Cressie bin is 2/(.457+.494/3+.045/9); first Dowd bin is 4.396.",
        [check("pair_counts",[3,2,1]),check("matheron",[2,8,18]),check("cressie_hawkins/0",2/(.457+.494/3+.045/9)),check("dowd/0",4.396)],
        "GeoHPGLDirectionalSemivariogram computes a directional classical estimate. This single comparison tool diagnoses sensitivity to outliers using two robust estimators on identical isotropic pair bins; algorithms are not counted separately.",
        "Projected metres only; no geodesic correction or directional search. Stationarity and representative sampling remain scientific assumptions. Empty bins remain null with zero counts.")
    st_values=[[2*x+3*t for t in range(4)] for x in range(4)]
    add("GeoSKGstatSpaceTimeVariogram","space_time_variogram","scikit-gstat","Estimate joint spatial/temporal geological semivariance from repeated fixed-station measurements, including both cross-time directions.",
        "skgstat.SpaceTimeVariogram","skgstat/SpaceTimeVariogram.py",
        {"coordinates_m":matrix("Distinct fixed station x,y coordinates in metres.",2,4,32),"values_by_station_time":matrix("Rows are stations, columns equally spaced times; complete measurements only.",minimum=4,maximum=32),"time_step_days":num("Explicit equal interval between observations.",exclusiveMinimum=0,maximum=1e6),"spatial_lags":integer("Number of spatial bins.",1,12),"temporal_lags":integer("Number of temporal bins.",1,12),"value_unit":UNITS},
        {"spatial_upper_edges":array("Inclusive spatial lag upper edges."),"temporal_upper_edges":array("Inclusive temporal lag upper edges in days."),"semivariance":matrix("Space-by-time semivariance; null for empty cells.",nullable=True,maximum=12),"pair_counts":array("Space-by-time counts including both time orderings.",array("Temporal bin counts.",integer("Pair count.",0,100000),1,12),1,12)},
        {"spatial_upper_edges":"m","temporal_upper_edges":"day","semivariance":GAMMA_UNITS,"pair_counts":"count"},
        {"coordinates_m":spatial_args["coordinates_m"],"values_by_station_time":st_values,"time_step_days":2,"spatial_lags":3,"temporal_lags":3,"value_unit":"ppm"},
        {"coordinates_m":[[0,0]]*4},
        "For z(x,t)=2x+3t, averaging forward/backward time pairs cancels cross terms, giving gamma(h,k)=(4h^2+9k^2)/2. First cell=6.5 ppm^2, opposite corner=58.5; first count=2*3*3=18.",
        [check("semivariance/0/0",6.5),check("semivariance/2/2",58.5),check("pair_counts/0/0",18),check("temporal_upper_edges",[2,4,6])],
        "Existing HPGL directional variograms use a single-time spatial point set. This estimates a two-dimensional space-time lag surface from repeat monitoring.",
        "Equal time spacing, complete data and fixed stations required. Excludes zero-space and zero-time pairs. Upstream marginal fits occur during construction but are not used as scientific outputs. Both time orderings are evaluated because the release's single ordering is asymmetric.")
    hs=[0,1,2,3,4,6]
    add("GeoGSToolsVariogramFit","exponential_variogram_fit","gstools","Fit correlated variance and correlation length to a supplied measured exponential semivariogram with fixed known nugget.",
        "gstools.Exponential.fit_variogram","src/gstools/covmodel/fit.py",
        {"lag_centers_m":array("Increasing empirical lag centers in metres.",num("Lag.",minimum=0,maximum=1e9),5,64),"semivariance":array("Aligned measured semivariances.",num("Squared-unit semivariance.",minimum=0,maximum=1e20),5,64),"fixed_nugget":num("Known fixed nugget; not fitted.",minimum=0,maximum=1e20),"value_unit":UNITS},
        {"correlated_variance":num("Fitted partial sill."),"length_scale_m":num("Exponential e-folding length, not the effective range."),"nugget":num("Fixed supplied nugget."),"fitted_semivariance":array("Fitted curve at input lags."),"r_squared":num("Fit R squared.")},
        {"correlated_variance":GAMMA_UNITS,"length_scale_m":"m","nugget":GAMMA_UNITS,"fitted_semivariance":GAMMA_UNITS,"r_squared":"1"},
        {"lag_centers_m":hs,"semivariance":[.25+2*(1-math.exp(-h/3)) for h in hs],"fixed_nugget":.25,"value_unit":"ppm"},
        {"lag_centers_m":[0,1,1,3,4,6]},
        "Analytically constructed gamma(h)=.25+2*(1-exp(-h/3)) identifies variance=2 ppm^2, length=3 m and fixed nugget=.25 ppm^2; R squared=1.",
        [check("correlated_variance",2,atol=1e-4),check("length_scale_m",3,atol=1e-4),check("r_squared",1,atol=1e-7)],
        "Neither the baseline empirical variogram nor prediction-grid kriging exposes an independent constrained fit to externally supplied empirical bins.",
        "One isotropic exponential family, fixed nugget and unweighted least squares. Parameter covariance must be finite; goodness of fit is not evidence of stationarity or prediction accuracy.")
    add("GeoGSToolsBlockSupportCovariance","block_support_covariance","gstools","Regularize point covariance to two explicit finite discrete geological sampling supports.",
        "gstools.Exponential.covariance","src/gstools/covmodel/models.py",
        {"support_a_m":matrix("Unique equally weighted 3D nodes defining support A.",3,1,128),"support_b_m":matrix("Unique equally weighted 3D nodes defining support B.",3,1,128),"point_variance":num("Correlated point variance, squared value units.",exclusiveMinimum=0,maximum=1e20),"length_scale_m":num("Isotropic exponential e-folding length.",exclusiveMinimum=0,maximum=1e9),"value_unit":UNITS},
        {"variance_a":num("Variance of support-A mean."),"variance_b":num("Variance of support-B mean."),"cross_covariance":num("Covariance of support means."),"difference_variance":num("Variance of mean-A minus mean-B.")},
        {"variance_a":GAMMA_UNITS,"variance_b":GAMMA_UNITS,"cross_covariance":GAMMA_UNITS,"difference_variance":GAMMA_UNITS},
        {"support_a_m":[[0,0,0],[2,0,0]],"support_b_m":[[1,0,0],[3,0,0]],"point_variance":4,"length_scale_m":1,"value_unit":"ppm"},
        {"support_a_m":[[0,0,0],[0,0,0]]},
        "With C(h)=4exp(-h), averaging the four within-block covariances gives 2+2exp(-2); between nodes {0,2} and {1,3}, covariance is 3exp(-1)+exp(-3).",
        [check("variance_a",2+2*math.exp(-2)),check("variance_b",2+2*math.exp(-2)),check("cross_covariance",3*math.exp(-1)+math.exp(-3))],
        "Existing point kriging predicts at locations; this quantifies change of sampling support through covariance regularization, without producing kriging predictions or reserves.",
        "Exact for the supplied equally weighted discrete nodes, only an approximation to a continuous block. Isotropic stationary exponential covariance and zero nugget are explicit; no inferred grade.")
    add("GeoSKGstatKrigingLOO","kriging_leave_one_out","scikit-gstat","Measure leave-one-out interpolation errors for a supplied fixed spherical geological variogram, retaining every validation fold.",
        "skgstat.OrdinaryKriging.transform","skgstat/Kriging.py",
        {**SPATIAL,"effective_range_m":num("Spherical effective range exceeding every pair distance.",exclusiveMinimum=0,maximum=1e9),"partial_sill":num("Correlated variance in squared units.",minimum=0,maximum=1e20),"nugget":num("Nugget in squared units.",minimum=0,maximum=1e20)},
        {"held_out_predictions":array("One prediction with that observation excluded."),"residuals":array("Prediction minus held-out observation."),"rmse":num("RMSE across ALL held-out samples."),"mean_error":num("Mean signed error.")},
        {"held_out_predictions":["ppm","wt_percent","dimensionless"],"residuals":["ppm","wt_percent","dimensionless"],"rmse":["ppm","wt_percent","dimensionless"],"mean_error":["ppm","wt_percent","dimensionless"]},
        {"coordinates_m":[[0,0],[1,0],[0,1],[1,1]],"values":[1,2,3,4],"value_unit":"ppm","effective_range_m":10,"partial_sill":0,"nugget":1},
        {"effective_range_m":.5},
        "Pure-nugget ordinary kriging gives equal weights to the three training points: predictions [3,8/3,7/3,2], errors [2,2/3,-2/3,-2], RMSE=sqrt(20/9).",
        [check("held_out_predictions",[3,8/3,7/3,2]),check("rmse",math.sqrt(20/9))],
        "GeoOrdinaryKrigingGrid generates prediction rasters. This tool removes each observation before prediction and measures held-out error; it does not duplicate a new grid/prediction API.",
        "The model must be fixed independently of validation data. All samples must fit within its range, no duplicate locations, at most 32 observations, and any failed fold fails the whole call.")
    bg=[math.exp(-math.sqrt(3)),1,math.exp(math.sqrt(3))]
    add("GeoGeochemBackgroundDistance","geochemical_background_distance","scikit-learn","Measure multivariate chemical departure from a caller-declared background in nonredundant ILR coordinates.",
        "sklearn.covariance.EmpiricalCovariance.mahalanobis","sklearn/covariance/_empirical_covariance.py",
        {"components":CHEM["components"],"samples":matrix("Positive tested compositions.",maximum=128,positive=True),"background":matrix("Independent positive background compositions.",minimum=3,maximum=256,positive=True),"basis":matrix("Orthonormal zero-sum ILR contrasts.",maximum=11),"input_unit":CHEM["input_unit"]},
        {"squared_mahalanobis":array("Squared distance; not a probability or mineral grade."),"background_ilr_mean":array("Estimated ILR mean."),"background_ilr_covariance":matrix("Maximum-likelihood covariance with 1/N normalization.")},
        {"squared_mahalanobis":"1","background_ilr_mean":"orthonormal_ln_ratio","background_ilr_covariance":"ln_ratio^2"},
        {"components":["Cu","Zn"],"samples":[[math.exp(2*math.sqrt(2)),1]],"background":[[b,1] for b in bg],"basis":[[1/math.sqrt(2),-1/math.sqrt(2)]],"input_unit":"ppm"},
        {"background":[[1,1]]*3},
        "Background log ratios map to [-sqrt(3/2),0,sqrt(3/2)] with ML variance 1; the sample maps to ILR=2, so squared Mahalanobis distance=4.",
        [check("squared_mahalanobis/0",4),check("background_ilr_covariance/0/0",1)],
        "GeoGeochemCLR transforms a composition but does not compare observations against an independently declared multivariate background. This emits a covariance-normalized anomaly score, not another transform.",
        "Empirical covariance is not robust to background contamination. Background selection is the caller's scientific responsibility; no automatic anomaly probability, ore label, cutoff or grade. Rejects singular/ill-conditioned backgrounds.","unsupported_conditions")
    curve_record=obj({"mnemonic":string("LAS curve mnemonic."),"unit":string("Unit read from LAS metadata."),"values":array("Original curve values with declared LAS nulls as JSON null.",NULLNUM,2,10000),"valid_count":integer("Finite sample count."),"null_count":integer("Declared-null sample count.")})
    add("GeoLasioLogAudit","las_log_audit","lasio","Parse and audit a local LAS drillhole log with explicit depth/curve units and preserved missing-value masks.",
        "lasio.LASFile.read","lasio/las.py",{"las_path":string("Task-relative local UTF-8 LAS file; maximum 2 MB.")},
        {"depth_m":array("Strictly increasing depth samples in metres.",minimum=2,maximum=10000),"row_count":integer("Number of depth rows.",2,10000),"curves":array("Measurement curves excluding the depth index.",curve_record,1,31)},
        {"depth_m":"m","row_count":"count","curve_values":"per_curve_explicit_unit"},
        {"las_path":ASSET+"/synthetic-log.las"}, {"las_path":ASSET+"/synthetic-nonmonotone.las"},
        "Synthetic LAS depths [100,101,102] and assay [10,NULL,30] must yield row_count=3, valid_count=2, null_count=1 and unaltered positive values 10 and 30.",
        [check("row_count",3),check("curves/0/valid_count",2),check("curves/0/null_count",1),check("curves/0/values/2",30)],
        "Baseline CSV record search and log/profile plotting do not parse LAS header/null conventions or enforce measured-depth integrity.",
        "Local UTF-8 LAS only, declared metre depths, no repair substitutions, no unit guessing, no interpolation or null filling. Numeric null masks are preserved; every measurement curve must state units.",paths=["las_path"])
    add("GeoWellyMinimumCurvature","drillhole_minimum_curvature","welly","Reconstruct a drillhole trajectory and normalized dogleg severity from a measured deviation survey.",
        "welly.tools.compute_position_log","welly/tools.py",
        {"survey_md_inc_azi":matrix("Rows: measured depth (m), inclination from downward vertical (degrees), azimuth clockwise from north (degrees). Starts at MD=0.",3,2,256)},
        {"east_north_tvd":matrix("Collar-relative easting, northing and positive-down true vertical depth.",3),"dogleg_severity":array("Upstream station dogleg severity in degrees per 30 m."),"measured_depth":array("Unaltered survey MD in metres.")},
        {"east_north_tvd":"m","dogleg_severity":"degree/30m","measured_depth":"m"},
        {"survey_md_inc_azi":[[0,0,90],[100,60,90]]}, {"survey_md_inc_azi":[[10,0,90],[100,60,90]]},
        "A 100-m circular arc from vertical to 60 degrees east has east=150/pi m, TVD=150sqrt(3)/pi m and dogleg severity 60/100*30=18 degrees/30m.",
        [check("east_north_tvd/1/0",150/math.pi),check("east_north_tvd/1/2",150*math.sqrt(3)/math.pi),check("dogleg_severity/1",18)],
        "Existing geographic distance/bearing tools do not integrate borehole deviation surveys or compute true vertical depth and dogleg severity.",
        "Minimum-curvature trajectory, not geodesy. Requires a measured collar station at MD zero; no automatic surface/TD station, azimuth correction or extrapolation. Welly delegates numerical integration to wellpathpy.")
    log_args={"depth_m":[0,1,2],"values":[10,20,30],"value_unit":"ppm"}
    add("GeoWellyLogResample","log_depth_resample","welly","Resample a measured drillhole log onto a declared regular depth basis using bounded linear interpolation.",
        "welly.Curve.to_basis","welly/curve.py",
        {**LOG,"start_m":num("First requested depth.",minimum=0,maximum=1e7),"stop_m":num("Last requested depth.",minimum=0,maximum=1e7),"step_m":num("Positive depth step.",exclusiveMinimum=0,maximum=1e7)},
        {"depth_m":array("Returned depth basis.",minimum=2,maximum=10000),"resampled_values":array("Interpolated values, not new observations.",minimum=2,maximum=10000)},
        {"depth_m":"m","resampled_values":["ppm","wt_percent","dimensionless"]}, {**log_args,"start_m":0,"stop_m":2,"step_m":.5}, {"stop_m":3},
        "For measured y=10+10z at depths 0,1,2 m, resampling at half-metre increments gives [10,15,20,25,30].",
        [check("resampled_values",[10,15,20,25,30]),check("depth_m",[0,.5,1,1.5,2])],
        "GeoHoloViewsLineProfile only renders supplied data. This constructs an explicit numeric depth basis for aligning logs before cross-log analysis.",
        "Interpolation is declared, bounded to observed endpoints and does not fill missing values. No inferred assay/ore grade; input arrays must already be complete.")
    add("GeoWellyLogDespike","log_median_despike","welly","Attenuate isolated drillhole-log spikes using an explicit median window and global standard-deviation threshold, retaining original values.",
        "welly.Curve.despike","welly/curve.py",
        {**LOG,"window_samples":integer("Odd median-window length in samples.",3,101),"standard_deviation_multiplier":num("Positive threshold times global population standard deviation.",exclusiveMinimum=0,maximum=10)},
        {"depth_m":LOG["depth_m"],"original_values":LOG["values"],"filtered_values":LOG["values"],"changed_indices":array("Modified zero-based sample positions.",integer("Index.",0,9999),0,10000)},
        {"depth_m":"m","original_values":["ppm","wt_percent","dimensionless"],"filtered_values":["ppm","wt_percent","dimensionless"],"changed_indices":"zero_based_index"},
        {"depth_m":[0,1,2,3,4],"values":[10,10,30,10,10],"value_unit":"ppm","window_samples":3,"standard_deviation_multiplier":1}, {"window_samples":4},
        "Values [10,10,30,10,10] have population standard deviation 8; the central rolling median is 10, so z=1 clips the central spike to 18 while all others remain 10.",
        [check("filtered_values",[10,10,18,10,10]),check("changed_indices",[2]),check("original_values/2",30)],
        "Baseline log visualization and general record cleaning do not apply a depth-indexed numerical spike filter with explicit thresholds and retained raw measurements.",
        "A signal-processing edit, not geological truth. Uses the upstream global standard deviation, not a robust local MAD. Regular sampling required; preserve raw values for audit.")
    add("GeoWellyLogFaciesBlock","log_facies_block","welly","Segment a measured drillhole log at caller-specified value cutoffs and compute mean values within contiguous blocks.",
        "welly.Curve.block","welly/curve.py",
        {**LOG,"cutoffs":array("Strictly increasing classification cutoffs in log units; intervals include their lower edge.",num("Explicit cutoff.",minimum=-1e12,maximum=1e12),1,16),"class_labels":labels("Declared class labels, one more than the cutoff count.",2,17)},
        {"depth_m":LOG["depth_m"],"class_indices":array("Numeric class indices aligned to samples.",integer("Zero-based class.",0,16),2,10000),"class_labels":labels("Caller-defined class semantics."),"block_mean_values":LOG["values"],"original_values":LOG["values"]},
        {"depth_m":"m","class_indices":"zero_based_class","block_mean_values":["ppm","wt_percent","dimensionless"],"original_values":["ppm","wt_percent","dimensionless"]},
        {"depth_m":[0,1,2,3,4],"values":[10,14,25,29,10],"value_unit":"ppm","cutoffs":[20],"class_labels":["SYNTHETIC_LOW","SYNTHETIC_HIGH"]}, {"values":[10,11,12,13,14]},
        "At cutoff 20, contiguous classes are [0,0,1,1,0]. Block means are [12,12,27,27,10], retaining the last low block separately from the first.",
        [check("class_indices",[0,0,1,1,0]),check("block_mean_values",[12,12,27,27,10])],
        "This creates a contiguous-zone representation and within-zone log means, unlike profile rendering or isolated-spike filtering. It is not a count of selections or a generic threshold-only wrapper.",
        "Classes and cutoffs are user declarations, not inferred lithology or mineralization. Requires at least two contiguous zones because the pinned upstream reducer has a single-zone defect; no local replacement formula is used.","unsupported_conditions")
    interval=obj({"top_m":num("Top measured depth.",minimum=0,maximum=1e7),"base_m":num("Base measured depth, greater than top.",minimum=0,maximum=1e7),"label":string("Observed interval label.",maxLength=80)})
    intersection=obj({"left_label":string("Left observed label."),"right_label":string("Right observed label."),"top_m":num("Intersection top."),"base_m":num("Intersection base."),"thickness_m":num("Intersection length along measured depth.")})
    add("GeoStriplogIntervalIntersection","drillhole_interval_intersection","striplog","Intersect two measured interval logs in one drillhole to expose co-occurring geological units and their shared measured-depth support.",
        "striplog.Interval.intersect","striplog/interval.py",
        {"hole_id":string("Explicit shared hole identifier; both interval sets use the same MD datum."),"left_intervals":array("Ordered, internally nonoverlapping observed intervals.",interval,1,128),"right_intervals":array("Ordered, internally nonoverlapping observed intervals.",interval,1,128)},
        {"hole_id":string("Unchanged shared hole identifier."),"intersections":array("Positive-length overlaps only.",intersection,0,16384),"total_overlap_m":num("Total shared MD support without double-counting.")},
        {"interval_depths":"m","total_overlap_m":"m"},
        {"hole_id":"SYNTHETIC_HOLE","left_intervals":[{"top_m":0,"base_m":10,"label":"SYNTHETIC_UNIT_A"}],"right_intervals":[{"top_m":4,"base_m":8,"label":"SYNTHETIC_UNIT_B"}]},
        {"left_intervals":[{"top_m":10,"base_m":0,"label":"SYNTHETIC_REVERSED"}]},
        "Measured-depth intervals [0,10] and [4,8] intersect at [4,8], giving thickness and total shared support exactly 4 m.",
        [check("intersections/0/top_m",4),check("intersections/0/base_m",8),check("intersections/0/thickness_m",4),check("total_overlap_m",4)],
        "Existing spatial polygon overlays work in map coordinates. This intersects geological logs along one shared borehole measured-depth datum, retaining both lithology labels and interval support.",
        "Same drillhole and MD datum are mandatory caller declarations. Along-hole thickness is not true stratigraphic thickness; boundary-only contacts contribute zero support. No ore or grade inference.")
    return rows


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False)+"\n", encoding="utf-8")


def provenance_schema(tool_id, source, requirements):
    versions = {p.split("==")[0]: {"type":"string","const":p.split("==")[1]} for p in requirements}
    digest = {"type":"string","pattern":"^[0-9a-f]{64}$"}
    return obj({"tool":{"const":tool_id,"type":"string"},"upstream_url":{"const":source["repository"],"type":"string"},
                "source_mode":{"const":"package_release","type":"string"},"reviewed_archive_commit":{"const":source["source_commit"],"type":"string"},
                "installed_versions":obj(versions),"vendored_source":array("No vendored numerical source.",string("Unused."),0,0),
                "input_sha256":digest,"implementation_sha256":digest,"contract_sha256":digest,"output_sha256":obj({}),
                "network_required":{"const":False,"type":"boolean"},"runtime_source_correspondence":string("Native contract's release/archive correspondence qualification.",maxLength=1000)})


def metadata(source):
    return {"asset_version":"1.0.0","provider":source["repository"].split("/")[-2],"license":source["license"],"upstream_license":source["license"],
            "source_url":source["repository"],"source_commit":source["source_commit"],"official_protocol_version":None,
            "official_protocol":{"applicability":"not_applicable","name":None,"version":None},"metadata_profile":"scientific",
            "runtime":{"python":"==3.12.*","dependency_lock":DELIVERY+"/requirements.txt","environment_version":"github-expansion-geology-20261025"},
            "lifecycle":{"registration":"source_authored_unverified","contract_validation":"not_run","unit_validation":"not_run","workflow_validation":"not_run","platform_validation":"not_run","release_status":"draft"},
            "pending_fields":["adapter_license","receiving_lab_approval","private_cpu_acceptance"],"platform_validation":"not_run"}


def main():
    preserve_previous_generated_sources()
    source_document=json.loads((GROUP/"sources.json").read_text(encoding="utf-8"))
    sources={r["package"]:r for r in source_document["repositories"]}
    rows=records()
    tools,examples,cases,candidates=[],{},{},[]
    for row in rows:
        name=row["tool_id"]
        source=sources[row["package"]]
        requirements=list(dict.fromkeys(BASE+DEPS[row["package"]]))
        unit_props={key:({"type":"string","enum":value} if isinstance(value,list) else {"type":"string","const":value}) for key,value in row["units"].items()}
        outputs=obj({**row["outputs"],"input_source":string("Unaltered caller-declared measurement provenance."),"units":obj(unit_props),
                     "artifacts":array("These numeric/read-only operations produce no files.",string("Unused."),0,0),"provenance":provenance_schema(name,source,requirements)})
        definition={"type":"function","function":{"name":name,"description":row["scientific_task"],"parameters":row["input_schema"]}}
        api_url=source["repository"]+"/blob/"+source["source_commit"]+"/"+row["api_path"]
        limitations=[row["limitation"],"All supplied fixtures are synthetic, not field/mineral evidence.","NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Private CPU acceptance and receiving-lab approval remain pending.","No arbitrary code, user-selected upstream callable, runtime dependency installation or network fetch."]
        spec={"id":name,"name":name,"description":row["scientific_task"],"input_schema":row["input_schema"],"output_schema":outputs,
              "constraints":{"finite_numbers_only":True,"no_automatic_dependency_install":True,"no_implicit_reprojection":True,"max_json_bytes":4000000,"max_file_bytes":2000000,"no_grade_imputation":True},
              "metadata":{"category":"github_expansion_geology","input_format":"Explicit bounded JSON measurements with units; LAS operation reads one declared local file.","output_format":"Strict scientific JSON with units and native provenance; no generated artifacts.","source":source["repository"],
                          "upstream":{"package":row["package"],"version":source["version"],"license":source["license"],"url":source["repository"],"source_mode":"package_release","requirements":requirements,"source_commit":source["source_commit"],"api_url":api_url,"upstream_callable":row["upstream_callable"],"license_evidence":source["license_url"]},
                          "scientific_contract":{"implementation_kind":"upstream_library","review_status":"acceptance_pending","formal_eligible":False,"numeric_oracle":row["numeric_oracle"],"oracle_source":DELIVERY+"/oracle-cases.json","synthetic_fixtures":True,"execution_status":"NOT TESTED","deployment_status":"NOT DEPLOYED","submission_status":"NOT SUBMITTED"}},
              "category":"github_expansion_geology","function":definition,"function_definition":copy.deepcopy(definition),"version":"1.0.0",
              "example_arguments":row["arguments"],"example_arguments_path":ASSET+"/"+name+".json","limitations":limitations,
              "source_interface":{"status":"source_revised_unverified","kind":"github_expansion_geology","path_fields":row["path_fields"],"network_required":False,"pure":not row["path_fields"],"validation":"acceptance_pending","entrypoint":{"callable":MODULE+":"+row["function"],"argument_parameter":"args","bound_arguments":{}}},
              "error_contract":{"direct_exception":"ScientificToolError","fields":["code","message","retryable"],"codes":["invalid_arguments","missing_input","missing_dependency","incompatible_dependency","resource_limit","invalid_input","invalid_result","invalid_path","empty_input","unsupported_conditions","output_conflict","upstream_failure"],"retry_policy":"Correct measurements, model assumptions or private dependency installation before retrying."},
              "tags":["geology","scientific","source-only",row["package"]],"registration_metadata":metadata(source)}
        tools.append(spec)
        examples[name]=row["arguments"]
        cases[name]={"tool_id":name,"function":row["function"],"arguments_path":ASSET+"/"+name+".json","arguments":row["arguments"],"checks":row["checks"],"numeric_oracle":row["numeric_oracle"],"negative_arguments":row["negative_arguments"],"negative_code":row["negative_code"],"status":"source_authored_unverified","synthetic":True}
        candidates.append({"tool_id":name,"capability_key":"geology:"+row["function"].replace("_","-"),"upstream_callable":row["upstream_callable"],"scientific_task":row["scientific_task"],"distinct_from_existing":row["distinct_from_existing"],"numeric_oracle":row["numeric_oracle"],"status":"source_authored_unverified"})
        dump(ROOT/ASSET/(name+".json"),row["arguments"])
    tool_by_id = {tool["id"]: tool for tool in tools}
    groups = [(key, title, [tool_by_id[name] for name in names]) for key, title, names in WORKFLOWS]
    skills=[]
    for key,title,group in groups:
        names=[t["id"] for t in group]
        description=" ".join(t["description"] for t in group)
        skill_path="catalog/skills/"+key+"/SKILL.md"
        reg=copy.deepcopy(group[0]["registration_metadata"])
        reg.update(provider="GeoAgent",license=None,upstream_license=None,source_commit=None,pending_fields=["adapter_license","receiving_lab_approval","private_cpu_acceptance"])
        skill={"id":key,"name":title,"description":description,"tool_references":names,"skill_file":skill_path,
               "metadata":{"canonical_skill_file":skill_path,"validation":"not_run","context_policy":f"Load only this coherent {len(names)}-operation workflow when relevant; progressive loading engine unchanged."},
               "delivery":{"source_candidates":names,"unavailable_references":[],"availability_status":"tool_candidates_available_workflow_unverified","workflow_validation":"not_run","deployment_status":"not_deployed","submission_status":"not_submitted","model_workflow_validation":"not_run","receiving_lab_approval":"pending"},"registration_metadata":reg}
        skills.append(skill)
        front="---\nid: "+key.replace("-","_")+"\nname: "+json.dumps(title)+"\ndescription: "+json.dumps(description)+"\nwhen_to_use: "+json.dumps(title+" from explicit supplied geological measurements")+"\ntools:\n"+"".join("- "+n+"\n" for n in names)
        front+="required_inputs:\n- Explicit measured data, units, source and scientific assumptions\nconstraints:\n- Use only the operation needed for the question\n- Preserve missingness, units, source hashes and uncertainty\n- Do not infer ore grade, reserves or mineral identity\n- No installation, online fetch or arbitrary Python at call time\nexpected_outputs:\n- Numeric scientific evidence and native provenance\n---\n"
        body="\n# "+title+"\n\n## When to use\n\n"+description+"\n\n## Required inputs\n\nUse the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.\n\n## Procedure\n\n1. Select the operation matching the scientific question and read its limitations.\n2. Obtain the declared measurements, units, reference compositions or model parameters.\n3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.\n4. Invoke the named native function with args as a dictionary or JSON object string.\n5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.\n\n## Tools and synthetic examples\n\n"
        for t in group:
            body+="### "+t["id"]+"\n\n"+t["description"]+"\n\nEntrypoint: `"+t["source_interface"]["entrypoint"]["callable"]+"`. Example: `"+t["example_arguments_path"]+"`. All examples are explicitly SYNTHETIC.\n\n"+t["limitations"][0]+"\n\nUpstream source: [pinned implementation]("+t["metadata"]["upstream"]["api_url"]+").\n\n"
        body+="## Interpretation and constraints\n\nThese calls use named upstream scientific kernels. A numerical result does not authenticate input data or establish geological representativeness. No tool infers ore grade, reserves or mineral presence. Synthetic examples are numerical oracles only. Units and structural/depth conventions are part of the measurement model.\n\n## Native errors\n\nScientificToolError exposes code, message and retryable. Correct invalid arguments or unsupported assumptions before retrying. missing_dependency and incompatible_dependency require the parent-controlled private worker; the tool never changes the environment. A failed scientific kernel returns an error, never a local substitute formula or placeholder value.\n\n## Source interface and delivery\n\nKind: github_expansion_geology. Module: geological_agent.geology.github_expansion_geology. Functions accept args=dict or args=JSON-object-string through collection_contracts.operation. No operation in this Skill requires output_dir or writes artifacts; the LAS reader alone reads one declared local file. Native provenance records pinned dependencies, source commit, input hash, implementation hash, contract hash, and empty artifact hashes.\n\n## Acceptance evidence\n\nPositive independent analytic oracles, per-operation negative constraints and provenance assertions are authored in `tests_local/test_github_expansion_geology.py` and `"+DELIVERY+"/oracle-cases.json`. They have NOT BEEN RUN. This r2 source has NOT BEEN TESTED. Parent reports a separate successful SQLAlchemy 1.4.54 / APSG 2.0.6 / ObsPy 1.4.2 joint import; that is not scientific acceptance of these operations.\n\n## Current availability\n\nSource authored and generated metadata only. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Unit, workflow, model-workflow and platform validation: not_run. Receiving-lab approval and adapter license: pending. Bingham axial confidence and CIPW normative mineralogy are blocked and excluded from all five active Skills; see the group blocked-operations.json. Parent owns fixed module whitelist, worker dispatch, registry integration and CPU acceptance. Existing online229 is unchanged.\n"
        target=ROOT/skill_path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(front+body,encoding="utf-8")
    dump(GROUP/"catalog-additions.json",{"tools":tools,"skills":skills})
    dump(GROUP/"examples-additions.json",examples)
    dump(GROUP/"candidate-operations.json",{"group":"geology","operations":candidates})
    dump(GROUP/"oracle-cases.json",{"group":"geology","status":"NOT TESTED","synthetic":True,"cases":cases})
    pins=list(dict.fromkeys(BASE+[p for values in DEPS.values() for p in values]))
    (GROUP/"requirements.txt").write_text("# Private CPU acceptance only. Python 3.12. Do not downgrade the shared environment.\n# APSG remains 2.0.6 for all eleven active APSG tools. Bingham is blocked and isolated.\n# Retain typing-extensions 4.16.0, pydantic 2.13.5, langgraph 1.2.12 and ObsPy 1.4.2.\n# Scientific/direct dependency profile; parent must freeze any remaining transitive utilities.\n"+"\n".join(pins)+"\n",encoding="utf-8")
    las="~Version Information\nVERS. 2.0 : CWLS LAS version\nWRAP. NO : Unwrapped\n~Well Information\nSTRT.M 100 : Start\nSTOP.M 102 : Stop\nSTEP.M 1 : Step\nNULL. -999.25 : Null\nWELL. SYNTHETIC_HOLE : Synthetic acceptance only\n~Curve Information\nDEPT.M : Measured depth\nCU.PPM : Synthetic concentration; not an assay\n~Parameter Information\n~Other\nSYNTHETIC numerical fixture. Not geological observations.\n~ASCII\n100 10\n101 -999.25\n102 30\n"
    (ROOT/ASSET/"synthetic-log.las").write_text(las,encoding="utf-8")
    (ROOT/ASSET/"synthetic-nonmonotone.las").write_text(las.replace("101 -999.25","100 -999.25"),encoding="utf-8")
    (ROOT/ASSET/"README.md").write_text("# Synthetic geology fixtures\n\nThe 28 active operation JSON files are explicitly synthetic analytic acceptance data, NOT field observations or mineral evidence. Blocked Bingham/CIPW arguments have been preserved in the historical group snapshot and are not active examples. Per-tool JSON files contain complete example arguments. The two LAS files are synthetic positive and negative fixtures. No fixture is an ore-grade, reserve, mineral-identification or geological-validation result. Status: NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.\n",encoding="utf-8")
    receipt={"group":"geology","revision":"r2","authored_tools":len(tools),"candidate_tools":len(tools),"blocked_tools":list(BLOCKED_IDS),"target_deficit":len(BLOCKED_IDS),"verified_in_this_revision":0,"authored_skills":len(skills),"status":"source_authored_unverified","testing":"NOT TESTED","deployment":"NOT DEPLOYED","submission":"NOT SUBMITTED","global_registry_modified":False,"shared_environment_modified":False,"module":MODULE,"source_interface_kind":"github_expansion_geology","requirements":pins,"known_blockers":source_document["blockers"]}
    dump(GROUP/"delivery-status.json",receipt)
    print(json.dumps({"source_metadata_generated":True,"tools":len(tools),"skills":len(skills),"blocked":list(BLOCKED_IDS),"tests_run":False,"deployment_performed":False}))


if __name__ == "__main__":
    main()
