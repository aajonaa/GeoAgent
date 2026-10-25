"""Generate disjoint geophysics source artifacts with standard library only.
NOT a test runner. No imports of numerical kernels, registry edits or network.
"""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
GROUP = Path(__file__).resolve().parent
ASSET = "assets/github-expansion-geophysics"
DELIVERY = "catalog/source_delivery/github-expansion-20261025/groups/geophysics"
MODULE = "geological_agent.geology.github_expansion_geophysics"
STATUS = "source_authored_unverified"
SYNTHETIC = "SYNTHETIC analytic fixture; not geological observations"
BASE = ["numpy==2.1.3", "scipy==1.15.3", "jsonschema==4.25.1"]
ROCK = BASE + ["pandas==2.3.0", "matplotlib==3.10.7", "KDE-diffusion==1.0.5"]
EQUINOR = BASE + ["pandas==2.3.0", "matplotlib==3.10.7", "scikit-learn==1.7.2", "tmatrix==1.2.0", "typing-extensions==4.16.0"]
BLOCKED_IDS = {"GeoRockStressAnisotropy"}
SOURCES = {
 "rock-physics-open":{"version":"1.0.1","repository":"equinor/rock-physics-open","commit":"68cd21b6a581e591d78ef90003292444cb81fe81","tag":"v1.0.1","license":"LGPL-3.0","license_file":"LICENSE","requirements":EQUINOR,"docs":"https://github.com/equinor/rock-physics-open/tree/v1.0.1/src/rock_physics_open/shale_models","compatibility":"Published Python>=3.11,<3.15 and dependency lower bounds admit the retained CPU baseline; actual r2 acceptance NOT RUN. Preserve typing-extensions4.16.0, pydantic2.13.5, langgraph1.2.12 and all shared pins. tmatrix1.2.0 has official CPython3.12 Linux/Windows wheels."},
 "choclo": {"version":"0.3.2","repository":"fatiando/choclo","commit":"6b4171701a6c8d7ffff88efc83c6bab5655233c3","tag":"v0.3.2","license":"BSD-3-Clause","license_file":"LICENSE.txt","requirements":["numpy==2.1.3","numba==0.68.0","jsonschema==4.25.1"],"docs":"https://www.fatiando.org/choclo/v0.3.2/api/index.html","compatibility":"Published numpy>=1.19,numba>=0.52. Supplied Python3.12/NumPy2.1.3/Numba0.68.0 acceptance NOT TESTED; no downgrade."},
 "rockphypy":{"version":"0.0.2","repository":"yujiaxin666/rockphypy","commit":"54c89027fb99e00b53761a05fcd7c20bc796ce7e","tag":"V0.0.2","license":"GPL-3.0","license_file":"LICENSE","requirements":ROCK,"docs":"https://rockphypy.readthedocs.io/en/latest/autoapi/rockphypy/index.html","compatibility":"Published lower bounds admit the supplied stack but do not prove compatibility. Package initialization imports KDE-diffusion. Private CPU installation/acceptance pending; retain GPLv3."},
 "bruges":{"version":"0.5.4","repository":"agilescientific/bruges","commit":"24e2e7912f49089465dd622363fd2788029266b1","tag":"v0.5.4","license":"Apache-2.0","license_file":"LICENSE.txt","requirements":BASE,"docs":"https://code.agilescientific.com/bruges/api/bruges.reflection.html","compatibility":"User-provided installed pin retained. New scattering entrypoint NOT TESTED."},
}
PINS = list(dict.fromkeys(BASE+ROCK+EQUINOR+["numba==0.68.0"]+[p+"=="+s["version"] for p,s in SOURCES.items()]))
ROWS=[]

def obj(props, required=None):
 return {"type":"object","properties":props,"required":list(props) if required is None else required,"additionalProperties":False}
def num(desc, lo=-1e20, hi=1e20, positive=False):
 return {"type":"number","description":desc,"exclusiveMinimum" if positive else "minimum":lo,"maximum":hi}
def arr(items, lo=1, hi=256, description="Ordered scientific values."):
 return {"type":"array","items":items,"minItems":lo,"maxItems":hi,"description":description}
def mat(items, rows=256, columns=3, description="Rows in the declared order."):
 return arr(arr(items,columns,columns),1,rows,description)
def txt(desc):
 return {"type":"string","description":desc,"minLength":1,"maxLength":1024}
def out(unit, shape=()):
 s=num("Scientific output in "+unit+".")
 for n in reversed(shape): s=arr(s,1 if n is None else n,256 if n is None else n)
 return {"unit":unit,"schema":s}
def check(path,value,rtol=1e-7,atol=1e-12):
 return {"path":[path] if isinstance(path,str) else path,"value":value,"relative_tolerance":rtol,"absolute_tolerance":atol}
def iso(k,g):
 lam=k-2*g/3
 return [[(lam+2*g if i==j else lam) if i<3 and j<3 else (g if i==j else 0) for j in range(6)] for i in range(6)]
def add(id,fn,pkg,call,task,inputs,outputs,example,expected,negative,oracle,distinct,limits,file):
 ROWS.append(dict(tool_id=id,function=fn,package=pkg,upstream_callable=call,scientific_task=task,inputs=inputs,outputs=outputs,example={"input_source":SYNTHETIC,**example},expected=expected,negative=negative,numeric_oracle=oracle,distinct_from_existing=distinct,limitations=limits,source_file=file))
GPA=num("Elastic modulus in GPa.",0,1000,True)
NONNEG=num("Inclusion modulus in GPa; zero denotes a cavity.",0,1000)
FRAC=num("Dimensionless volume fraction.",0,1)
PHI=num("Dimensionless connected porosity.",0,0.7,True)
RHO=num("Density in kg/m^3.",10,20000)
COORD=num("Local Cartesian ENU coordinate in metres; no CRS transform.",-1e7,1e7)
C=arr(arr(num("Stiffness in GPa.",-1000,1000),6,6),6,6,"Symmetric positive-definite 6x6 stiffness; engineering Voigt order 11,22,33,23,13,12.")
PRESS=num("Positive effective confining stress in MPa.",0,1000,True)
VEL=num("Velocity in m/s.",1,20000)
FREQ=arr(num("Frequency in Hz.",0.001,1000),1,128)
FRAME={"dry_bulk_gpa":GPA,"dry_shear_gpa":GPA,"mineral_bulk_gpa":GPA,"porosity":PHI}
GRAIN={"bulk_gpa":GPA,"shear_gpa":GPA}
PACK={**GRAIN,"porosity":PHI,"coordination":num("Mean grain coordination number.",3,16)}
FLOW={"permeability_m2":num("Supplied intrinsic rock permeability in m^2.",1e-16,1e-8),"mineral_density_kg_m3":RHO}
MOD={"bulk_gpa":out("GPa"),"shear_gpa":out("GPa")}
NEAR="Original229 SeismicReflectivity computes acoustic interface contrast, not constitutive rock properties. "

def records():
 grav=6.6743e-11
 mu0=1.25663706212e-6
 pts={"observations_enu_m":mat(COORD),"sources_enu_m":mat(COORD,64)}
 pris={"observations_enu_m":mat(COORD),"prisms_wesnbt_m":mat(COORD,64,6,"Prism bounds west,east,south,north,bottom,top in metres; upward positive.")}
 fields={"potential_j_kg":out("J/kg",(None,)),"acceleration_enu_m_s2":out("m/s^2",(None,3)),"gradient_enu_s2":out("s^-2",(None,3,3))}
 add("GeoPointMassGravity","point_mass_gravity","choclo","choclo.point.gravity_pot",
 "Forward-model potential, acceleration and full gravity-gradient tensor of point mass contrasts.",
 {**pts,"masses_kg":arr(num("Signed mass contrast in kg.",-1e18,1e18),1,64)},fields,
 {"observations_enu_m":[[0,0,10]],"sources_enu_m":[[0,0,0]],"masses_kg":[1e9]},
 [check(["potential_j_kg",0],grav*1e8),check(["acceleration_enu_m_s2",0,2],-grav*1e7),check(["gradient_enu_s2",0,2,2],2*grav*1e6)],
 {"observations_enu_m":[[0,0,0]]},
 "Independent Newton solution at r=10m,m=1e9kg: V=Gm/r, gu=-Gm/r^2, Tuu=2Gm/r^3.",
 "No source gravity forward model in original229; GeoMagnitudeToEnergy concerns earthquake energy, not gravitational sources.",
 ["Point-source idealization; >=1mm separation; all components bundled; no density inversion."],"choclo/point/_forward.py")
 omega=4*(math.atan(1/(2*math.sqrt(6)))-math.atan(1/(4*math.sqrt(18))))
 add("GeoPrismGravity","prism_gravity","choclo","choclo.prism.gravity_pot",
 "Forward-model gravity and its full gradient tensor for finite rectangular density-contrast bodies.",
 {**pris,"density_contrast_kg_m3":arr(num("Signed density contrast in kg/m^3.",-30000,30000),1,64)},fields,
 {"observations_enu_m":[[0,0,3]],"prisms_wesnbt_m":[[-1,1,-1,1,-1,1]],"density_contrast_kg_m3":[1000]},
 [check(["gradient_enu_s2",0,2,2],grav*1000*omega),check(["gradient_enu_s2",0,0,0],-grav*500*omega)],
 {"prisms_wesnbt_m":[[1,-1,-1,1,-1,1]]},
 "Independent surface solid-angle identity for a 2m cube at z=3m: Tzz=G*rho*[Omega(2)-Omega(4)], Omega(d)=4atan[1/(d*sqrt(d^2+2))].",
 "No finite-body gravity in original229; finite-volume integration differs from point-source approximation.",
 ["Uniform density per prism; reject observations inside or on any closed prism; no inversion or inferred ore volume."],"choclo/prism/_gravity.py")
 add("GeoDipoleMagnetic","dipole_magnetic","choclo","choclo.dipole.magnetic_field",
 "Forward-model all magnetic induction components from explicit dipole moments.",
 {**pts,"moments_enu_a_m2":mat(num("ENU dipole moment in A*m^2.",-1e15,1e15),64)},
 {"magnetic_enu_t":out("T",(None,3))},
 {"observations_enu_m":[[0,0,10]],"sources_enu_m":[[0,0,0]],"moments_enu_a_m2":[[0,0,1000]]},
 [check(["magnetic_enu_t",0,2],mu0/(2*math.pi))],{"observations_enu_m":[[0,0,0]]},
 "Independent axial dipole Bz=mu0*m/(2*pi*r^3), m=1000A*m^2,r=10m.",
 "No magnetic forward model in original229; PyrockoDoubleCoupleTensor is a seismic moment tensor.",
 ["Dipole idealization; supplied moments; tesla, not nT; no susceptibility inference."],"choclo/dipole/_forward.py")
 add("GeoPrismMagnetic","prism_magnetic","choclo","choclo.prism.magnetic_field",
 "Forward-model magnetic induction vectors from uniformly magnetized finite prisms.",
 {**pris,"magnetization_enu_a_m":mat(num("ENU magnetization in A/m.",-1e6,1e6),64)},
 {"magnetic_enu_t":out("T",(None,3))},
 {"observations_enu_m":[[0,0,3]],"prisms_wesnbt_m":[[-1,1,-1,1,-1,1]],"magnetization_enu_a_m":[[0,0,1]]},
 [check(["magnetic_enu_t",0,2],mu0*omega/(4*math.pi))],{"observations_enu_m":[[0,0,0]]},
 "Independent bound magnetic-charge surface integral: Bz=mu0*M*[Omega_top-Omega_bottom]/(4*pi).",
 "No finite-volume magnetics in original229; source geometry differs physically from a point dipole at finite offsets.",
 ["Uniform supplied magnetization; reject interior/boundary observations; no geomagnetic retrieval or inversion."],"choclo/prism/_magnetic.py")
 add("GeoRockVRHBounds","rock_vrh_bounds","rockphypy","rockphypy.EM.EM.VRH",
 "Compute Voigt, Reuss and Hill bulk/shear estimates for a multiphase mineral aggregate.",
 {"fractions":arr(FRAC,2,32),"bulk_gpa":arr(GPA,2,32),"shear_gpa":arr(GPA,2,32)},
 {"bulk_vrh_gpa":out("GPa",(3,)),"shear_vrh_gpa":out("GPa",(3,))},
 {"fractions":[0.5,0.5],"bulk_gpa":[20,40],"shear_gpa":[10,20]},
 [check("bulk_vrh_gpa",[30,80/3,85/3]),check("shear_vrh_gpa",[15,40/3,85/6])],
 {"fractions":[0.5,0.4]},"Independent series/parallel energy bounds: harmonic/arithmetic means, then midpoint; output V,R,H.",
 NEAR+"Aggregate phase-energy bounds are absent.",["Isotropic phases; supplied volume fractions sum to one."],"rockphypy/EM.py")
 add("GeoRockHashinShtrikman","rock_hashin_shtrikman","rockphypy","rockphypy.EM.EM.HS",
 "Compute both Hashin-Shtrikman elastic bounds for a two-phase composite.",
 {"stiff_fraction":FRAC,"stiff_bulk_gpa":GPA,"soft_bulk_gpa":GPA,"stiff_shear_gpa":GPA,"soft_shear_gpa":GPA},
 {"bulk_bounds_gpa":out("GPa",(2,)),"shear_bounds_gpa":out("GPa",(2,))},
 {"stiff_fraction":0.5,"stiff_bulk_gpa":40,"soft_bulk_gpa":20,"stiff_shear_gpa":20,"soft_shear_gpa":10},
 [check("bulk_bounds_gpa",[360/13,480/17])],{"stiff_bulk_gpa":20},
 "Independent two-phase variational expressions at f=1/2 give K_lower=360/13,K_upper=480/17GPa.",
 NEAR+"Coupled elastic variational bounds are tighter than uncoupled VRH.",["Strictly ordered stiff/soft bulk and shear moduli; no automatic sorting."],"rockphypy/EM.py")
 add("GeoRockCriticalPorosity","rock_critical_porosity","rockphypy","rockphypy.EM.EM.cripor",
 "Predict load-bearing dry-frame moduli below critical porosity.",
 {**GRAIN,"porosity":FRAC,"critical_porosity":PHI},MOD,
 {"bulk_gpa":40,"shear_gpa":30,"porosity":0.1,"critical_porosity":0.4},
 [check("bulk_gpa",30),check("shear_gpa",22.5)],{"porosity":0.4},
 "Independent load-bearing fraction 1-phi/phi_c=3/4 gives K=30,G=22.5GPa.",
 NEAR+"Frame collapse with porosity differs from mineral-mixture bounds.",
 ["Only phi<phi_c; critical porosity must be supplied; no suspension branch."],"rockphypy/EM.py")
 add("GeoRockSphericalPores","rock_spherical_pores","rockphypy","rockphypy.EM.EM.Swiss_cheese",
 "Estimate elastic compliance added by dilute spherical dry pores.",
 {**GRAIN,"porosity":num("Dilute spherical pore fraction.",0,0.15)},MOD,
 {"bulk_gpa":20,"shear_gpa":15,"porosity":0.1},
 [check("bulk_gpa",50/3),check("shear_gpa",12.5)],{"porosity":0.3},
 "For K=20,G=15GPa the independent spherical pore compliance multiplier is 1+2phi=1.2 for both moduli.",
 NEAR+"Cavity compliance differs from critical-porosity collapse and phase mixing.",
 ["Noninteracting spherical cavities; porosity<=0.15; not a crack/high-porosity model."],"rockphypy/EM.py")
 add("GeoRockSelfConsistent","rock_self_consistent","rock-physics-open","rock_physics_open.shale_models.multi_sca.multi_sca",
 "Solve Berryman multiphase spheroidal self-consistency with unmodified Equinor geometry and dual constitutive convergence checks.",
 {"fractions":arr(FRAC,2,16),"bulk_gpa":arr(GPA,2,16),"shear_gpa":arr(GPA,2,16),"aspect_ratios":arr(num("Spheroid aspect ratio; exact 1 is a sphere, >1 prolate, <1 oblate.",0.05,5),2,16),"density_kg_m3":arr(RHO,2,16)},
 {**MOD,"density_kg_m3":out("kg/m^3"),"bulk_residual_pa":out("Pa"),"shear_residual_pa":out("Pa")},
 {"fractions":[0.5,0.5],"bulk_gpa":[4,16],"shear_gpa":[3,12],"aspect_ratios":[1,1],"density_kg_m3":[2400,2800]},
 [check("bulk_gpa",8,rtol=1e-6),check("shear_gpa",6,rtol=1e-6),check("density_kg_m3",2600)],{"fractions":[0.4,0.5]},
 "Heterogeneous exact spheres with K_i=4G_i/3 and equal fractions have P_i=Q_i at K=4G/3. The two self-consistency equations reduce to G^2=G1*G2=36: K=8,G=6 GPa, density=2600 kg/m3. Additional prolate and mixed-shape inverse-design analytic oracles are in r2-oracles.json.",
 NEAR+"Berryman coherent-potential self-consistency, not variational bounds or differential effective-medium accumulation.",
 ["Explicit phase densities, GPa->Pa conversion; exact spheres and prolates retained, with no equal-phase restriction.",
  "Upstream iteration stops on bulk change only and caps at 3000. Adapter checks BOTH weighted residuals <=1e-8 times their phase modulus scale and rejects nonconvergence without altering the kernel.",
  "Fractions must sum to 1 within 1e-12. No imputed densities; LGPL-3.0 dependency. R2 NOT TESTED."],"src/rock_physics_open/shale_models/multi_sca.py")
 nu=0.2*(1-16*0.05/9)
 add("GeoRockRandomCracks","rock_random_cracks","rockphypy","rockphypy.EM.EM.OConnell_Budiansky",
 "Predict isotropic elastic weakening by randomly oriented dry penny-shaped cracks.",
 {**GRAIN,"crack_density":num("Dimensionless crack number density times radius cubed.",0,0.1)},MOD,
 {"bulk_gpa":20,"shear_gpa":15,"crack_density":0.05},
 [check("bulk_gpa",20*(1-16*(1-nu*nu)*0.05/(9*(1-2*nu)))),check("shear_gpa",15*(1-32*(1-nu)*(5-nu)*0.05/(45*(2-nu))))],
 {"crack_density":0.3},"Independent O'Connell-Budiansky expression with nu0=1/5, corrected nu=41/225, crack density=1/20.",
 NEAR+"Random cracks yield isotropic weakening; Hudson predicts a full tensor for a resolved aligned fracture set.",
 ["Dry thin-crack approximation; crack density<=0.1; not an inversion."],"rockphypy/EM.py")
 add("GeoRockMoriTanaka","rock_mori_tanaka","rockphypy","rockphypy.EM.EM.MT_average",
 "Estimate composite moduli using a virtual matrix and modified Mori-Tanaka localization.",
 {"phase1_fraction":FRAC,"matrix_bulk_gpa":GPA,"matrix_shear_gpa":GPA,"phase1_bulk_gpa":GPA,"phase1_shear_gpa":GPA,"phase2_bulk_gpa":GPA,"phase2_shear_gpa":GPA},MOD,
 {"phase1_fraction":0.3,"matrix_bulk_gpa":30,"matrix_shear_gpa":20,"phase1_bulk_gpa":20,"phase1_shear_gpa":10,"phase2_bulk_gpa":20,"phase2_shear_gpa":10},
 [check("bulk_gpa",20),check("shear_gpa",10)],{"matrix_shear_gpa":0},
 "Equal-inhomogeneity limit: numerator is modulus times denominator, giving 20,10GPa even with a different virtual matrix.",
 NEAR+"Prescribed virtual-matrix localization differs from a self-consistent host or bounds.",
 ["Virtual matrix is a supplied physical modeling assumption, not fitted from data."],"rockphypy/EM.py")

 add("GeoRockHudsonCracks","rock_hudson_cracks","rockphypy","rockphypy.EM.EM.hudson",
 "Predict first-order VTI stiffness for aligned penny-shaped cracks.",
 {**GRAIN,"inclusion_bulk_gpa":NONNEG,"inclusion_shear_gpa":NONNEG,"aspect_ratio":num("Thin-crack aspect ratio.",0.0001,0.1),"crack_density":num("Dimensionless low crack density.",0,0.05)},
 {"stiffness_gpa":out("GPa",(6,6))},
 {"bulk_gpa":20,"shear_gpa":15,"inclusion_bulk_gpa":0,"inclusion_shear_gpa":0,"aspect_ratio":0.01,"crack_density":0.02},
 [check(["stiffness_gpa",2,2],40-1600*0.02*(160/75)/15),check(["stiffness_gpa",5,5],15)],
 {"aspect_ratio":0},"Independent dry-crack U3=32/15 for lambda=10,mu=15GPa; C33=40-(40^2/15)*0.02*U3,C66=15.",
 NEAR+"An aligned crack population produces anisotropic compliance; this is not a stereonet or orientation-only calculation.",
 ["Fixed first order and axis3; thin weak cracks; reject unstable tensors."],"rockphypy/EM.py")
 khm=(0.1*36*0.36*225/(18*math.pi**2*0.8**2))**(1/3)
 add("GeoRockHertzMindlin","rock_hertz_mindlin","rockphypy","rockphypy.GM.GM.hertzmindlin",
 "Predict confining-stress-dependent stiffness of an uncemented granular packing.",
 {**PACK,"effective_stress_mpa":PRESS,"shear_factor":FRAC},MOD,
 {"bulk_gpa":20,"shear_gpa":15,"porosity":0.4,"coordination":6,"effective_stress_mpa":100,"shear_factor":0},
 [check("bulk_gpa",khm),check("shear_gpa",0.6*khm)],{"effective_stress_mpa":0},
 "Independent Hertz contact scaling at P=0.1GPa: K^3=P*n^2*(1-phi)^2*G^2/[18*pi^2*(1-nu)^2],nu=.2; zero shear factor gives G_eff=3K_eff/5.",
 NEAR+"Pressure-dependent unbonded contacts differ from cement and porosity averaging.",
 ["Effective pressure in MPa; shear factor follows numeric upstream convention; no recovered stress."],"rockphypy/GM.py")
 alpha=2*(1/270)**0.25
 ln=(32/15)/math.pi
 cement_k=24*(-0.024153*ln**-1.3646*alpha**2+0.20405*ln**-0.89008*alpha+0.00024649*ln**-1.9864)
 add("GeoRockContactCement","rock_contact_cement","rockphypy","rockphypy.GM.GM.contactcement",
 "Estimate sandstone stiffness from cement deposited at grain contacts.",
 {**PACK,"critical_porosity":PHI,"cement_bulk_gpa":GPA,"cement_shear_gpa":GPA},MOD,
 {"bulk_gpa":20,"shear_gpa":15,"porosity":0.36,"critical_porosity":0.4,"coordination":6,"cement_bulk_gpa":20,"cement_shear_gpa":15},
 [check("bulk_gpa",cement_k)],{"porosity":0.41},
 "Independent Dvorkin-Nur contact polynomial evaluation: nu0=nuc=.2,alpha=2*(1/270)^(1/4),LambdaN=32/(15*pi),K_eff=24*S_n.",
 NEAR+"Cement elasticity and deposition geometry differ from pressure-only Hertz contacts or existing bonded areas.",
 ["Fixed contact-deposition scheme1; 0<phi_c-phi<=0.1; empirical contact polynomial."],"rockphypy/GM.py")
 pd=0.0025*2*6*0.6*15/(3*math.pi*0.8)*1000
 sn,st=4*15*math.sqrt(0.02)/0.8,8*15*0.1/1.8
 add("GeoRockDigbyContacts","rock_digby_contacts","rockphypy","rockphypy.GM.GM.Digby",
 "Predict granular moduli from pre-existing bonded contacts under stress.",
 {**PACK,"effective_stress_mpa":PRESS,"bond_radius_ratio":num("Bonded-area radius / grain radius.",0,0.3,True)},MOD,
 {"bulk_gpa":20,"shear_gpa":15,"porosity":0.4,"coordination":6,"effective_stress_mpa":pd,"bond_radius_ratio":0.1},
 [check("bulk_gpa",3.6*sn/(12*math.pi)),check("shear_gpa",3.6*(sn+1.5*st)/(20*math.pi))],
 {"effective_stress_mpa":-1},
 "Choose pressure making the positive contact cubic root exactly d=.1 with a/R=.1; b/R=sqrt(.02). Independent spring sums give bulk and shear.",
 NEAR+"Finite prebond tangential rigidity differs from unbonded Hertz and newly deposited cement.",
 ["Positive pressure avoids upstream zero-pressure complex-root ambiguity; bounded bond radius."],"rockphypy/GM.py")
 i0=(math.sqrt(2)+math.log(1+math.sqrt(2)))/2
 i2=(2*math.sqrt(2)-i0)/4
 i4=(2*math.sqrt(2)-3*i2)/6
 cn,ct=75,200/3
 bw,cw=2/(math.pi*cn),4/math.pi*(1/ct-1/cn)
 gamma=3/32*cn*ct*6*0.6*math.sqrt(0.001)
 add("GeoRockStressAnisotropy","rock_stress_anisotropy","rockphypy","rockphypy.GM.GM.johnson",
 "Predict VTI stiffness and stresses under simultaneous isotropic and axial compression.",
 {**PACK,"hydrostatic_strain":num("Negative compressive strain.",-0.02,-1e-6),"axial_strain":num("Negative additional axial compression.",-0.02,-1e-6)},
 {"stiffness_gpa":out("GPa",(6,6)),"stress_33_gpa":out("GPa"),"stress_11_gpa":out("GPa")},
 {"bulk_gpa":20,"shear_gpa":15,"porosity":0.4,"coordination":6,"hydrostatic_strain":-0.001,"axial_strain":-0.001},
 [check(["stiffness_gpa",2,2],gamma*(4*bw*i2+2*cw*i4))],{"axial_strain":0.001},
 "Equal compressive strains give alpha=1; independent angular integrals reduce to sqrt(2) and asinh(1)=ln(1+sqrt(2)); C33 evaluated from contact constants.",
 NEAR+"Loading-induced contact anisotropy differs from fractures and scalar hydrostatic Hertz stiffness.",
 ["Fixed simultaneous path; negative small strains; ratio[.1,10]; compressive stresses negative."],"rockphypy/GM.py")
 add("GeoRockSandShalePorosity","rock_sand_shale_porosity","rockphypy","rockphypy.GM.GM.ThomasStieber",
 "Predict dispersed and laminated sand-shale porosity envelopes.",
 {"sand_porosity":PHI,"shale_porosity":PHI,"shale_fraction":arr(FRAC)},
 {"dispersed_porosity":out("1",(None,)),"laminated_porosity":out("1",(None,))},
 {"sand_porosity":0.4,"shale_porosity":0.1,"shale_fraction":[0,0.2,0.6,1]},
 [check("dispersed_porosity",[0.4,0.22,0.06,0.1]),check("laminated_porosity",[0.4,0.34,0.22,0.1])],
 {"shale_porosity":0.5},
 "Independent volumetric geometry: laminated line joins .4 and .1; dispersed envelope intersects pore-filling and shale-framework lines.",
 NEAR+"Texture-controlled porosity is distinct from geochemical normalization and elastic mixture averaging.",
 ["Volume fractions only; no shale-volume inference from logs or chemical composition."],"rockphypy/GM.py")
 add("GeoRockGassmannSubstitution","rock_gassmann_substitution","rockphypy","rockphypy.Fluid.Fluid.Gassmann_sub",
 "Replace pore fluid in an isotropic low-frequency frame and report both saturated bulk moduli.",
 {**FRAME,"initial_fluid_bulk_gpa":GPA,"replacement_fluid_bulk_gpa":GPA},
 {"initial_bulk_gpa":out("GPa"),"replacement_bulk_gpa":out("GPa"),"shear_gpa":out("GPa")},
 {"dry_bulk_gpa":10,"dry_shear_gpa":8,"mineral_bulk_gpa":40,"porosity":0.25,"initial_fluid_bulk_gpa":4,"replacement_fluid_bulk_gpa":8},
 [check("initial_bulk_gpa",17.5),check("replacement_bulk_gpa",160/7),check("shear_gpa",8)],
 {"dry_bulk_gpa":45},
 "Independent Gassmann alpha=3/4; denominators3/40 and7/160 give Ksat1=17.5,Ksat2=160/7GPa; shear=8.",
 NEAR+"Changes saturant at fixed frame instead of evaluating an interface.",
 ["Connected equilibrated pores; unchanged dry frame and shear; no saturation inference."],"rockphypy/Fluid.py")
 add("GeoRockBrownKorringa","rock_brown_korringa","rockphypy","rockphypy.Fluid.Fluid.Brown_Korringa_dry2sat",
 "Saturate supplied anisotropic dry compliance using Brown-Korringa poroelasticity.",
 {"dry_stiffness_gpa":C,"mineral_bulk_gpa":GPA,"mineral_shear_gpa":GPA,"fluid_bulk_gpa":GPA,"porosity":PHI},
 {"saturated_stiffness_gpa":out("GPa",(6,6)),"saturated_compliance_inv_gpa":out("GPa^-1",(6,6))},
 {"dry_stiffness_gpa":iso(10,8),"mineral_bulk_gpa":40,"mineral_shear_gpa":30,"fluid_bulk_gpa":4,"porosity":0.25},
 [check(["saturated_stiffness_gpa",0,0],169/6),check(["saturated_stiffness_gpa",0,1],73/6),check(["saturated_stiffness_gpa",3,3],8)],
 {"fluid_bulk_gpa":50},
 "Independent isotropic Gassmann limit Ksat=17.5,G=8: C11=169/6,C12=73/6,C44=8GPa.",
 NEAR+"Full anisotropic compliance differs from scalar isotropic substitution.",
 ["Isotropic mineral assumption; engineering Voigt order; positive definite tensors."],"rockphypy/Fluid.py")
 vp_low=math.sqrt((17.5+32/3)*1e9/2237.5)
 vs_low=math.sqrt(8e9/2237.5)
 add("GeoRockBiotDispersion","rock_biot_dispersion","rockphypy","rockphypy.Fluid.Fluid.Biot",
 "Compute frequency-dependent fast/slow P waves, shear waves and Biot attenuation.",
 {**FRAME,**FLOW,"fluid_bulk_gpa":GPA,"fluid_density_kg_m3":RHO,"viscosity_pa_s":num("Fluid viscosity in Pa*s.",1e-5,0.1),"pore_radius_m":num("Hydraulic pore-size parameter in m.",1e-7,0.001),"tortuosity":num("Inertial tortuosity.",1,10),"frequencies_hz":FREQ},
 {k:out("m/s" if k.endswith("m_s") else "1",(None,)) for k in ("fast_p_m_s","slow_p_m_s","shear_m_s","fast_p_inverse_q","slow_p_inverse_q","shear_inverse_q")},
 {"dry_bulk_gpa":10,"dry_shear_gpa":8,"mineral_bulk_gpa":40,"porosity":0.25,"fluid_bulk_gpa":4,"mineral_density_kg_m3":2650,"fluid_density_kg_m3":1000,"permeability_m2":1e-12,"viscosity_pa_s":0.001,"pore_radius_m":1e-5,"tortuosity":2,"frequencies_hz":[0.01]},
 [check(["fast_p_m_s",0],vp_low,1e-4),check(["shear_m_s",0],vs_low,1e-4)],{"tortuosity":0.5},
 "Independent locked-fluid low-frequency limit: rho=2237.5kg/m3,Ksat=17.5GPa,G=8GPa. Expected sqrt((Ksat+4G/3)/rho) and sqrt(G/rho); 1e-4 relative tolerance at finite .01Hz.",
 NEAR+"Poroelastic slow wave and frequency loss are absent from static saturation and acoustic reflection.",
 ["Consistent SI kernel inputs yield m/s despite ambiguous upstream km/s prose.","Homogeneous isotropic medium; viscodynamic argument<=200; upstream complex loss convention."],"rockphypy/Fluid.py")
 vp_dry=math.sqrt((10+32/3)*1e9/2000)
 add("GeoRockSquirtFlow","rock_squirt_flow","rockphypy","rockphypy.Fluid.Fluid.Mavko_Jizba",
 "Predict high-frequency saturated properties from pressure-dependent dry velocities via squirt flow.",
 {"high_pressure_vp_m_s":VEL,"high_pressure_vs_m_s":VEL,"dry_vp_m_s":arr(VEL),"dry_vs_m_s":arr(VEL),"mineral_bulk_gpa":GPA,"dry_density_kg_m3":RHO,"fluid_density_kg_m3":RHO,"fluid_bulk_gpa":GPA,"porosity":PHI},
 {"saturated_bulk_gpa":out("GPa"),"saturated_shear_gpa":out("GPa",(None,)),"vp_m_s":out("m/s",(None,)),"vs_m_s":out("m/s",(None,))},
 {"high_pressure_vp_m_s":vp_dry,"high_pressure_vs_m_s":2000,"dry_vp_m_s":[math.sqrt(13e9/2000)],"dry_vs_m_s":[math.sqrt(6e9/2000)],"mineral_bulk_gpa":40,"dry_density_kg_m3":2000,"fluid_density_kg_m3":1000,"fluid_bulk_gpa":4,"porosity":0.25},
 [check("saturated_bulk_gpa",17.5),check(["saturated_shear_gpa",0],50/7),check(["vp_m_s",0],math.sqrt((17.5+200/21)*1e9/2250))],
 {"dry_vp_m_s":[1000]},
 "Nonzero crack compliance: Kdry=5,Gdry=6,Khigh=10,Ghigh=8 GPa. Independent Gwet=1/(1/6-(4/15)*(1/5-1/10))=50/7 GPa, Ksat=17.5 GPa and rho_sat=2250 kg/m3.",
 NEAR+"Compliant-pore high-frequency squirt limit differs from macroscopic Biot flow.",
 ["Require 0<Kdry<=Khigh<Kmineral, 0<Gdry<=Ghigh, and 1/Gdry-(4/15)*(1/Kdry-1/Khigh)>=1/Ghigh>0; velocity bounds alone are insufficient. Explicit kg/m3 to upstream g/cm3 conversion."],"rockphypy/Fluid.py")
 add("GeoRockPatchySaturation","rock_patchy_saturation","rockphypy","rockphypy.Fluid.Fluid.White_Dutta_Ode",
 "Compute P-wave dispersion and attenuation for concentric patches of two pore fluids.",
 {**FRAME,**FLOW,"inner_fluid_bulk_gpa":GPA,"outer_fluid_bulk_gpa":GPA,"inner_density_kg_m3":RHO,"outer_density_kg_m3":RHO,"inner_viscosity_pa_s":num("Inner-fluid viscosity Pa*s.",1e-5,0.1),"outer_viscosity_pa_s":num("Outer-fluid viscosity Pa*s.",1e-5,0.1),"inner_radius_m":num("Inner patch radius in m.",1e-5,0.1),"inner_saturation":num("Inner-fluid pore saturation.",0.01,0.99),"frequencies_hz":FREQ},
 {"vp_m_s":out("m/s",(None,)),"attenuation_inv_m":out("m^-1",(None,)),"bulk_real_gpa":out("GPa",(None,)),"bulk_imag_gpa":out("GPa",(None,))},
 {"dry_bulk_gpa":10,"dry_shear_gpa":8,"mineral_bulk_gpa":40,"porosity":0.25,"mineral_density_kg_m3":2650,"inner_fluid_bulk_gpa":4,"outer_fluid_bulk_gpa":4,"inner_density_kg_m3":1000,"outer_density_kg_m3":1000,"inner_viscosity_pa_s":0.001,"outer_viscosity_pa_s":0.001,"permeability_m2":1e-10,"inner_radius_m":0.01,"inner_saturation":0.5,"frequencies_hz":[1,10]},
 [check("vp_m_s",[vp_low,vp_low]),check("bulk_real_gpa",[17.5,17.5]),check("attenuation_inv_m",[0,0])],
 {"inner_saturation":0},
 "Independent equal-fluid limit cancels patch flow: positive K*=17.5GPa and vp=sqrt((17.5+32/3)*1e9/2237.5), with zero attenuation at both frequencies.",
 NEAR+"Spatial two-fluid patch relaxation differs from single-fluid Biot and compliant-crack squirt flow.",
 ["Concentric patches; supplied fluids/geometry; unstable exponential regimes rejected; no patch-size inversion."],"rockphypy/Fluid.py")
 add("GeoRockBrieMixing","rock_brie_mixing","rockphypy","rockphypy.Fluid.Fluid.Brie",
 "Predict effective liquid-gas bulk modulus versus saturation using the Brie mixing law.",
 {"liquid_bulk_gpa":GPA,"gas_bulk_gpa":GPA,"liquid_saturation":arr(FRAC),"exponent":num("Calibrated Brie exponent.",1,10)},
 {"fluid_bulk_gpa":out("GPa",(None,))},
 {"liquid_bulk_gpa":2.5,"gas_bulk_gpa":0.1,"liquid_saturation":[0,0.5,1],"exponent":2},
 [check("fluid_bulk_gpa",[0.1,0.7,2.5])],{"gas_bulk_gpa":3},
 "Independent polynomial K=.1+2.4*S^2 gives .1,.7,2.5GPa at S=0,.5,1.",
 NEAR+"Pore-fluid constitutive mixing differs from rock substitution and patch-scale dynamics.",
 ["Empirical exponent supplied, not fitted; no saturation inference."],"rockphypy/Fluid.py")
 rw=1.0048567
 vw=1402.85+1.524*10+0.003437*100-0.00001197*1000
 rb=rw+0.1*(0.668+0.044+0.0006)
 vb=vw+(1170+26-4.76)*0.1+(780-100+16)*0.1**1.5-820*0.01
 add("GeoRockFluidPVT","rock_fluid_pvt","rockphypy","rockphypy.BW.BW.rho_K_brine",
 "Evaluate Batzle-Wang water, brine, oil and gas density and acoustic bulk moduli.",
 {"temperature_c":num("Temperature Celsius; conservative correlation range.",0,150),"pressure_mpa":num("Pressure MPa.",0.1,100),"salinity_mass_fraction":num("NaCl mass fraction, not ppm.",0,0.2),"reference_oil_density_kg_m3":num("Reference oil density kg/m3.",650,1050),"gas_specific_gravity":num("Gas density relative to air.",0.55,1.2)},
 {"density_water_brine_oil_gas_kg_m3":out("kg/m^3",(4,)),"bulk_water_brine_oil_gas_gpa":out("GPa",(4,))},
 {"temperature_c":0,"pressure_mpa":10,"salinity_mass_fraction":0.1,"reference_oil_density_kg_m3":850,"gas_specific_gravity":0.7},
 [check(["density_water_brine_oil_gas_kg_m3",0],rw*1000),check(["density_water_brine_oil_gas_kg_m3",1],rb*1000),check(["bulk_water_brine_oil_gas_gpa",0],rw*vw*vw/1e6),check(["bulk_water_brine_oil_gas_gpa",1],rb*vb*vb/1e6)],
 {"pressure_mpa":101},
 "At T=0C,P=10MPa independent water polynomial rho=1.0048567g/cm3 and velocity cubic; evaluate brine salinity terms independently, then K=rho*v^2.",
 NEAR+"Reservoir-fluid acoustic properties are absent; all fluid species are bundled as one tool.",
 ["Empirical PVT, not phase-equilibrium calculation; conservative pressure/temperature limits; no gas/oil identification."],"rockphypy/BW.py")

 add("GeoSeismicBackus","seismic_backus","rockphypy","rockphypy.Anisotropy.Anisotropy.Backus",
 "Upscale fine isotropic layering to five long-wavelength VTI stiffnesses.",
 {"fractions":arr(FRAC,2,64),"lame_lambda_gpa":arr(num("Positive first Lame parameter GPa.",0,1000,True),2,64),"shear_gpa":arr(GPA,2,64)},
 {"c11_c33_c13_c44_c66_gpa":out("GPa",(5,))},
 {"fractions":[0.5,0.5],"lame_lambda_gpa":[10,20],"shear_gpa":[10,20]},
 [check("c11_c33_c13_c44_c66_gpa",[400/9,40,40/3,40/3,15])],{"fractions":[0.4,0.4]},
 "Independent layered compliance: C33=harmonic(30,60)=40,C44=harmonic(10,20)=40/3,C66=15; lambda/(lambda+2G)=1/3 gives C13=40/3,C11=400/9.",
 "Original229 SeismicReflectivity operates at interfaces; Backus homogenizes subwavelength layers into anisotropy.",
 ["Layers must be thin relative to wavelength; supplied fractions sum to one; no inferred wavelength validity."],"rockphypy/Anisotropy.py")
 vti=iso(20,15)
 vti[0][0]=vti[1][1]=44
 vti[0][1]=vti[1][0]=14
 add("GeoSeismicVTIPhase","seismic_vti_phase","rockphypy","rockphypy.Anisotropy.Anisotropy.vel_azi_VTI",
 "Compute quasi-P, quasi-SV and SH phase velocities versus inclination in a VTI rock.",
 {"stiffness_gpa":C,"density_kg_m3":RHO,"inclination_degrees":arr(num("Wave-normal inclination from vertical axis in degrees, not geographic azimuth.",0,90))},
 {"vp_m_s":out("m/s",(None,)),"vsh_m_s":out("m/s",(None,)),"vsv_m_s":out("m/s",(None,))},
 {"stiffness_gpa":vti,"density_kg_m3":2500,"inclination_degrees":[0,90]},
 [check("vp_m_s",[4000,math.sqrt(44e9/2500)]),check("vsh_m_s",[math.sqrt(15e9/2500)]*2)],
 {"density_kg_m3":0},
 "Principal-direction Christoffel diagonalization: vertical P=sqrt(C33/rho)=4000m/s,horizontal P=sqrt(C11/rho),SH=sqrt(15GPa/rho).",
 "Original229 has reflection and seismic moment tensors, not anisotropic propagation; all wave modes remain one tool.",
 ["Phase speeds, not group speeds; upstream azimuth argument physically denotes inclination in this VTI formula."],"rockphypy/Anisotropy.py")
 orth=[[48,16,14,0,0,0],[16,44,12,0,0,0],[14,12,40,0,0,0],[0,0,0,10,0,0],[0,0,0,0,12,0],[0,0,0,0,0,14]]
 add("GeoSeismicOrthorhombicParameters","seismic_orthorhombic_parameters","rockphypy","rockphypy.Anisotropy.Anisotropy.Thomsen_Tsvankin",
 "Extract seven Thomsen-Tsvankin anisotropy parameters from a supplied orthorhombic stiffness tensor.",
 {"stiffness_gpa":C},{"epsilon1_delta1_gamma1_epsilon2_delta2_gamma2_delta3":out("1",(7,))},
 {"stiffness_gpa":orth},
 [check("epsilon1_delta1_gamma1_epsilon2_delta2_gamma2_delta3",[0.05,-416/2400,1/12,0.1,-108/2240,0.2,-256/3264])],
 {"stiffness_gpa":[[0]*6 for _ in range(6)]},
 "Independent stiffness contrasts: eps1=(44-40)/80=.05,eps2=.1,gamma1=1/12,gamma2=.2; delta terms are the stated rational square contrasts.",
 "Original229 lacks constitutive anisotropy characterization; this resolves three orthorhombic symmetry planes rather than VTI wave propagation.",
 ["Symmetry-aligned tensor; no rotation; extracting parameters does not guarantee weak anisotropy."],"rockphypy/Anisotropy.py")
 add("GeoSeismicHTIReflectivity","seismic_hti_reflectivity","rockphypy","rockphypy.AVO.AVO.AVO_HTI",
 "Compute Ruger PP reflectivity versus incidence and azimuth for two weakly anisotropic HTI layers.",
 {"upper_stiffness_gpa":C,"lower_stiffness_gpa":C,"upper_density_kg_m3":RHO,"lower_density_kg_m3":RHO,"incidence_degrees":arr(num("Incident upper-layer qP phase angle; <=35 degrees AND strictly subcritical for the actual two-layer tensors/densities.",0,35),1,64),"azimuth_degrees":arr(num("Azimuth from horizontal HTI axis in degrees.",0,360),1,64)},
 {"pp_reflectivity_azimuth_by_angle":out("1",(None,None))},
 {"upper_stiffness_gpa":iso(20,15),"lower_stiffness_gpa":iso(24.2,18.15),"upper_density_kg_m3":2500,"lower_density_kg_m3":2500,"incidence_degrees":[0,20],"azimuth_degrees":[0,90]},
 [check(["pp_reflectivity_azimuth_by_angle",0,0],1/21),check(["pp_reflectivity_azimuth_by_angle",1,0],1/21)],
 {"incidence_degrees":[60]},
 "Independent isotropic normal-incidence limit: equal density and vp=4,4.4km/s give R=(4.4-4)/(4.4+4)=1/21 at each azimuth.",
 "SeismicReflectivity is normal-incidence acoustic contrast; this takes full HTI stiffness and resolves fracture-sensitive azimuthal AVO.",
 ["Ruger approximation; incidence<=35deg AND actual anisotropic transmission must be strictly propagating. Christoffel vertical-slowness domain gate rejects critical/evanescent modes at each supplied azimuth; it does not replace upstream amplitudes. Weak anisotropy<=.2; aligned HTI axes; not fracture inversion."],"rockphypy/AVO.py")
 add("GeoSeismicZoeppritzScattering","seismic_zoeppritz_scattering","bruges","bruges.reflection.reflection.scattering_matrix",
 "Compute complete complex P/S reflection and transmission matrices at an elastic interface.",
 {"upper_vp_m_s":VEL,"upper_vs_m_s":VEL,"upper_density_kg_m3":RHO,"lower_vp_m_s":VEL,"lower_vs_m_s":VEL,"lower_density_kg_m3":RHO,"incidence_degrees":arr(num("Incidence degrees; complex post-critical outputs retained.",0,80),1,128)},
 {"scattering_real":out("1",(None,4,4)),"scattering_imag":out("1",(None,4,4))},
 {"upper_vp_m_s":2000,"upper_vs_m_s":1000,"upper_density_kg_m3":2000,"lower_vp_m_s":3000,"lower_vs_m_s":1500,"lower_density_kg_m3":2000,"incidence_degrees":[0,30,60]},
 [check(["scattering_real",0,0,0],0.2),check(["scattering_real",0,0,2],0.8)],
 {"upper_vs_m_s":2000},
 "Independent normal-incidence displacement/traction continuity with impedance ratio3/2 gives R=1/5,transmitted displacement=4/5; postcritical output is not discarded.",
 "SeismicReflectivity is scalar acoustic contrast; full elastic converted/transmitted modes and complex critical-angle behavior are distinct.",
 ["Lossless isotropic elastic halfspaces; no fluid halfspace; incident rows Pd,Sd,Pu,Su and outgoing columns Pu,Su,Pd,Sd."],"bruges/reflection/reflection.py")
 add("GeoSeismicElasticImpedance","seismic_elastic_impedance","rockphypy","rockphypy.AVO.AVO.EI_ref",
 "Construct normalized PP, PSV, SVP, SVSV and SHSH angle-dependent elastic impedance logs.",
 {"vp_m_s":arr(VEL,2,128),"vs_m_s":arr(VEL,2,128),"density_kg_m3":arr(RHO,2,128),"incidence_degrees":arr(num("Incidence degrees.",0,40),1,64),"shear_p_ratio":num("Supplied constant reference Vs/Vp.",0.2,0.7)},
 {k:out("kg/(m^2*s)",(None,None)) for k in ("pp","psv","svp","svsv","shsh")},
 {"vp_m_s":[2000,3000],"vs_m_s":[1000,1500],"density_kg_m3":[2000,2200],"incidence_degrees":[0,20],"shear_p_ratio":0.5},
 [check(["pp",0,0],4e6),check(["pp",1,0],6.6e6)],{"vs_m_s":[3000,1500]},
 "Independent normalized PP zero-angle limit is rho*Vp=4e6 and6.6e6kg/(m^2*s).",
 "SeismicReflectivity returns interface coefficients; elastic impedance creates angle-dependent multicomponent property logs for inversion parameterization.",
 ["Mean normalization is specific to supplied logs; explicit Vs/Vp reference; no inversion or geological classification."],"rockphypy/AVO.py")


def provenance_schema(source, requirements):
 installed={r.split("==")[0]:{"const":r.split("==")[1]} for r in requirements}
 digest={"type":"string","pattern":"^[0-9a-f]{64}$"}
 return obj({
  "tool":txt("Tool identifier."),"upstream_url":{"const":"https://github.com/"+source["repository"]},
  "source_mode":{"const":"package_release"},"reviewed_archive_commit":{"const":source["commit"]},
  "installed_versions":obj(installed),"vendored_source":{"type":"array","items":{"type":"string"},"maxItems":0},
  "input_sha256":digest,"implementation_sha256":digest,"contract_sha256":digest,
  "output_sha256":obj({}),"network_required":{"const":False},
  "runtime_source_correspondence":txt("Contract notice distinguishing reviewed source from installed distribution verification.")})

def dump(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,indent=2,ensure_ascii=True,allow_nan=False)+"\n",encoding="utf-8")

def meta(s):
 return {"asset_version":"1.0.1","provider":s["repository"].split("/")[0],
  "license":None,"upstream_license":s["license"],"source_url":"https://github.com/"+s["repository"],"source_commit":s["commit"],
  "official_protocol_version":None,"official_protocol":{"applicability":"not_applicable","name":None,"version":None},
  "metadata_profile":"scientific","runtime":{"python":"==3.12.*","dependency_lock":DELIVERY+"/requirements-geophysics.txt","environment_version":"github-expansion-geophysics-20261025-r2"},
  "lifecycle":{"registration":"not_submitted","contract_validation":"not_run","unit_validation":"not_run","workflow_validation":"not_run","platform_validation":"not_run","release_status":"draft"},
  "pending_fields":["adapter_license","receiving_lab_approval","private_cpu_acceptance"],"platform_validation":"not_run","deployment_status":"not_deployed","submission_status":"not_submitted"}


def _oracle_inverse(matrix):
 """Small Kelvin-system inverse for fixture construction, not a model solver."""
 size=len(matrix)
 work=[list(row)+[float(i==j) for j in range(size)] for i,row in enumerate(matrix)]
 for column in range(size):
  pivot=max(range(column,size),key=lambda i:abs(work[i][column]))
  work[column],work[pivot]=work[pivot],work[column]
  divisor=work[column][column]
  work[column]=[v/divisor for v in work[column]]
  for row in range(size):
   if row!=column:
    scale=work[row][column]
    work[row]=[v-scale*w for v,w in zip(work[row],work[column])]
 return [row[size:] for row in work]

def _oracle_hill_factors(bulk,shear,phase_bulk,phase_shear,aspect):
 """Independent angular-moment Hill tensor, not upstream scalar PQ formulas.

 Parnell (2016), DOI 10.1007/s10659-016-9573-6, sections 3.2,3.3,
 Appendix A.2 and rotational projections. Closed angular moments are derived
 in independent-oracles.md. No scientific package is imported.
 """
 if aspect==1:
  second,fourth=1/3,1/5
 elif aspect>1:
  b=aspect*aspect-1
  logterm=math.log(aspect+math.sqrt(b))
  second=aspect*logterm/b**1.5-1/b
  fourth=(aspect*aspect+2)/(2*b*b)-3*aspect*logterm/(2*b**2.5)
 else:
  b=1-aspect*aspect
  angle=math.acos(aspect)
  second=1/b-aspect*angle/b**1.5
  fourth=(aspect*aspect+2)/(2*b*b)-3*aspect*angle/(2*b**2.5)
 def moment2(i,j):
  return (second if i==2 else (1-second)/2) if i==j else 0
 def moment4(i,j,k,l):
  indices=(i,j,k,l)
  counts=[indices.count(axis) for axis in range(3)]
  if any(n%2 for n in counts):
   return 0
  if counts[2]==4:
   return fourth
  if counts[2]==2:
   return (second-fourth)/2
  return (3/8 if 4 in counts else 1/8)*(1-2*second+fourth)
 lam=bulk-2*shear/3
 beta=(lam+shear)/(lam+2*shear)
 def hill(i,j,k,l):
  return ((i==k)*moment2(j,l)+(i==l)*moment2(j,k)
         +(j==k)*moment2(i,l)+(j==l)*moment2(i,k)
         -4*beta*moment4(i,j,k,l))/(4*shear)
 basis=[[(0,0,1)],[(1,1,1)],[(2,2,1)],
        [(1,2,1/math.sqrt(2)),(2,1,1/math.sqrt(2))],
        [(0,2,1/math.sqrt(2)),(2,0,1/math.sqrt(2))],
        [(0,1,1/math.sqrt(2)),(1,0,1/math.sqrt(2))]]
 h=[[sum(x*y*hill(i,j,k,l) for i,j,x in ea for k,l,y in eb)
     for eb in basis] for ea in basis]
 # Kelvin shear entries are 2G; engineering-Voigt entries would be G.
 contrast=iso(phase_bulk-bulk,phase_shear-shear)
 for i in range(3,6):
  contrast[i][i]*=2
 system=[[float(i==j)+sum(h[i][k]*contrast[k][j] for k in range(6))
          for j in range(6)] for i in range(6)]
 concentration=_oracle_inverse(system)
 p=sum(concentration[i][j] for i in range(3) for j in range(3))/3
 q=(sum(concentration[i][i] for i in range(6))-p)/5
 return p,q

def _inverse_designed_sca(label,aspects):
 # Prescribe a nontrivial target, then solve linear volume-balance equations.
 # No self-consistent iteration and no upstream P/Q evaluation occurs here.
 bulk,shear,density=[4,16,8],[3,3,12],[2400,2700,3000]
 factors=[_oracle_hill_factors(8,6,k,g,a) for k,g,a in zip(bulk,shear,aspects)]
 d=[(k-8)*p for k,(p,q) in zip(bulk,factors)]
 e=[(g-6)*q for g,(p,q) in zip(shear,factors)]
 ratio2=-d[0]/d[1]
 ratio3=-(e[0]+ratio2*e[1])/e[2]
 weights=[1,ratio2,ratio3]
 fractions=[w/sum(weights) for w in weights]
 return {"case_id":label,"tool_id":"GeoRockSelfConsistent","synthetic":True,
  "arguments":{"input_source":SYNTHETIC,"fractions":fractions,"bulk_gpa":bulk,
   "shear_gpa":shear,"aspect_ratios":aspects,"density_kg_m3":density},
  "expected_checks":[check("bulk_gpa",8,rtol=1e-6),check("shear_gpa",6,rtol=1e-6),
   check("density_kg_m3",sum(f*r for f,r in zip(fractions,density)))],
  "independent_phase_factors_p_q":factors,
  "numeric_oracle":"Prescribed K*=8,G*=6 GPa; independent Hill/Kelvin concentration projections determine positive fractions algebraically so both weighted constitutive balances vanish. No upstream kernel outputs or nonlinear solver define expectations."}

def emit_r2_evidence():
 rows={r["tool_id"]:r for r in ROWS}
 sc=rows["GeoRockSelfConsistent"]
 sphere={"case_id":"heterogeneous_exact_spheres","tool_id":sc["tool_id"],"synthetic":True,
  "arguments":sc["example"],"expected_checks":sc["expected"],"numeric_oracle":sc["numeric_oracle"]}
 positive=[sphere,_inverse_designed_sca("heterogeneous_prolates",[2,3,2]),
           _inverse_designed_sca("heterogeneous_oblate_exact_sphere_prolate",[0.5,1,2])]
 negatives=[]
 def negative(label,tool,overrides,oracle,code="invalid_arguments"):
  args=copy.deepcopy(rows[tool]["example"])
  args.update(overrides)
  negatives.append({"case_id":label,"tool_id":tool,"synthetic":True,"arguments":args,
   "expected_error":code,"numeric_oracle":oracle})
 upper=iso(20,15)
 negative("hti_isotropic_postcritical","GeoSeismicHTIReflectivity",
  {"upper_stiffness_gpa":upper,"lower_stiffness_gpa":iso(80,60),
   "incidence_degrees":[35],"azimuth_degrees":[0]},
  "Equal density: Vp1=4000,Vp2=8000 m/s, critical angle=30deg; 35deg violates Snell propagation even though <=35deg schema limit.",
  "unsupported_conditions")
 negative("hti_isotropic_exact_critical","GeoSeismicHTIReflectivity",
  {"upper_stiffness_gpa":upper,"lower_stiffness_gpa":iso(80,60),
   "incidence_degrees":[30],"azimuth_degrees":[0]},
  "At 30deg the transmitted qP vertical slowness is zero; strictly propagating approximation excludes the critical boundary.",
  "unsupported_conditions")
 anisotropic=[[v*3.515625 for v in row] for row in upper]
 anisotropic[0][0]*=1.2
 negative("hti_actual_anisotropic_postcritical","GeoSeismicHTIReflectivity",
  {"upper_stiffness_gpa":upper,"lower_stiffness_gpa":anisotropic,
   "incidence_degrees":[30],"azimuth_degrees":[0]},
  "Lower epsilon=.1,delta=gamma=0. Horizontal qP speed=sqrt(168.75e9/2500)>8000 m/s, making 30deg postcritical. Vertical qP speed=7500 alone would incorrectly admit it.",
  "unsupported_conditions")
 negative("squirt_velocity_bounds_do_not_bound_bulk","GeoRockSquirtFlow",
  {"high_pressure_vp_m_s":4000,"high_pressure_vs_m_s":2500,
   "dry_vp_m_s":[3900],"dry_vs_m_s":[1800]},
  "At rho=2000, Khigh=46/3 GPa but Kdry=21.78 GPa despite both dry velocities being smaller.")
 negative("squirt_exceeds_crack_free_shear","GeoRockSquirtFlow",
  {"dry_vp_m_s":[math.sqrt((5+28/3)*1e9/2000)],"dry_vs_m_s":[math.sqrt(7e9/2000)]},
  "Kdry=5,Gdry=7,Khigh=10,Ghigh=8 GPa: predicted wet compliance=61/525 1/GPa, Gwet=525/61>8.")
 negative("squirt_negative_wet_shear_compliance","GeoRockSquirtFlow",
  {"dry_vp_m_s":[math.sqrt((1+28/3)*1e9/2000)],"dry_vs_m_s":[math.sqrt(7e9/2000)]},
  "Kdry=1,Gdry=7,Khigh=10 GPa: wet shear compliance=1/7-(4/15)*(1-1/10)=-17/175 1/GPa.")
 negative("sca_bulk_only_false_convergence","GeoRockSelfConsistent",
  {"bulk_gpa":[10,10],"shear_gpa":[3,12],"aspect_ratios":[1,1]},
  "Equal phase bulk moduli force zero bulk update immediately, but contrasting shear moduli leave a nonzero shear balance. Reject native premature convergence instead of changing the solver.",
  "invalid_result")
 dump(ROOT/ASSET/"r2-oracles.json",{"synthetic":True,"status":STATUS,"positive_cases":positive,
  "negative_cases":negatives,"oracle_source":"Parnell (2016), DOI 10.1007/s10659-016-9573-6, isotropic-host Hill tensor and concentration projections; independent closed angular moments.",
  "derivation":DELIVERY+"/independent-oracles.md","upstream_used_to_generate_expectations":False})
 blocked=rows["GeoRockStressAnisotropy"]
 dump(GROUP/"blocked-operations.json",{"group":"geophysics","operations":[{
  "tool_id":"GeoRockStressAnisotropy","status":"blocked_upstream_defect","registered":False,"counted":False,
  "reason":"GM.johnson logarithm parentheses disagree with the angular integral for unequal strains. No accepted maintained replacement.",
  "upstream_callable":blocked["upstream_callable"],"package_pin":"rockphypy==0.0.2",
  "reviewed_release_commit":SOURCES["rockphypy"]["commit"],
  "reviewed_latest_commit":"2f13920ac29d4fc45c3f8dfc0443688b76242271",
  "source_url":"https://github.com/yujiaxin666/rockphypy/blob/2f13920ac29d4fc45c3f8dfc0443688b76242271/rockphypy/GM.py",
  "historical_fixture":ASSET+"/GeoRockStressAnisotropy.json",
  "historical_source":DELIVERY+"/diagnostics/r1-stress-anisotropy-source.txt",
  "diagnostic_test":"TestBlockedStressAnisotropyDiagnostic.test_unequal_strain_angular_integral",
  "diagnostic_status":"expected_failure_source_authored_not_run",
  "prohibited_workarounds":["equal-strain-only admission","locally corrected upstream kernel","counting blocked diagnostics as operations"]}]})
 dump(GROUP/"r2-status.json",{"group":"geophysics","candidate_operations":29,"blocked_operations":1,
  "workflow_skills":5,"source_status":STATUS,"scientific_tests_run_by_this_agent":False,
  "parent_reported_r1":"30 basic numeric cases passed; later heterogeneous/geometry/logarithm counterexamples remain historical failures, not r2 evidence.",
  "parent_reported_private_dependencies":"rock_physics_open1.0.1/tmatrix1.2.0 source SHA, wheel ABI and requirements verified by parent with numpy2.1.3/scipy1.15.3/pandas2.3.0/typing-extensions4.16.0.",
  "historical_r1_reports":"Preserved unchanged; no historical acceptance is relabeled r2.",
  "unchanged_shared_pins":["SQLAlchemy==1.4.54","typing-extensions==4.16.0","pydantic==2.13.5","langgraph==1.2.12"],
  "deployment_status":"not_deployed","submission_status":"not_submitted",
  "remaining_blockers":["Parent joint CPU acceptance not yet reported for this source revision.",
    "GeoRockStressAnisotropy has no accepted upstream repair and remains excluded.",
    "Upstream multi_sca bulk-only convergence can cause valid inputs to be rejected by dual residual gate; no local solver patch is supplied.",
    "GPL/LGPL redistribution and adapter licensing review remains pending."]})
 (GROUP/"requirements-r2-additions.txt").write_text(
  "# Parent-reported installed private additions; no installation by this generator.\n"
  "rock-physics-open==1.0.1\ntmatrix==1.2.0\n"
  "# Retain typing-extensions==4.16.0 and all other baseline pins.\n"
  "# Complete direct profile: requirements-geophysics.txt\n",encoding="utf-8")


def build():
 ROWS.clear()
 records()
 tools,examples,candidates=[],{},[]
 for r in ROWS:
  if r["tool_id"] in BLOCKED_IDS:
   continue
  s=SOURCES[r["package"]]
  requirements=[r["package"]+"=="+s["version"]]+s["requirements"]
  schema=obj({"input_source":txt("Caller-declared measurement/model provenance; not independently authenticated."),**r["inputs"]})
  output=obj({"input_source":txt("Preserved caller provenance."),**{k:v["schema"] for k,v in r["outputs"].items()},
   "units":obj({k:{"const":v["unit"]} for k,v in r["outputs"].items()}),
   "artifacts":{"type":"array","items":{"type":"string"},"maxItems":0},"provenance":provenance_schema(s,requirements)})
  definition={"type":"function","function":{"name":r["tool_id"],"description":r["scientific_task"],"parameters":schema}}
  url="https://github.com/"+s["repository"]+"/blob/"+s["commit"]+"/"+r["source_file"]
  fixture=ASSET+"/"+r["tool_id"]+".json"
  limits=r["limitations"]+["NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Acceptance source exists but has not run.",
   "Synthetic fixtures are not observations, mineral identification, ore grade, resources or reserves.",
   "No network, automatic installation, arbitrary functions/code or scientific-kernel substitution."]
  spec={"id":r["tool_id"],"name":r["tool_id"],"description":r["scientific_task"],"input_schema":schema,"output_schema":output,
   "constraints":{"finite_numbers_only":True,"max_json_bytes":4000000,"no_automatic_dependency_install":True,"no_network":True,"max_observation_source_pairs":8192},
   "metadata":{"category":"github_expansion_geophysics","input_format":"Bounded JSON; units explicit in fields/descriptions","output_format":"Schema-validated numeric JSON; no files",
    "source":url,"example_path":fixture,
    "upstream":{"package":r["package"],"version":s["version"],"license":s["license"],"url":"https://github.com/"+s["repository"],
     "source_mode":"package_release","requirements":s["requirements"],"source_commit":s["commit"],"callable":r["upstream_callable"],"source_url":url,
     "license_url":"https://github.com/"+s["repository"]+"/blob/"+s["commit"]+"/"+s["license_file"]},
    "scientific_contract":{"implementation_kind":"upstream_library","review_status":"acceptance_pending","formal_eligible":False,"numeric_oracle":r["numeric_oracle"],"distinct_from_existing":r["distinct_from_existing"]}},
   "category":"github_expansion_geophysics","function":definition,"function_definition":copy.deepcopy(definition),"version":"1.0.1",
   "example_arguments":r["example"],"example_path":fixture,"limitations":limits,
   "source_interface":{"status":"source_revised_unverified","kind":"github_expansion_geophysics","path_fields":[],"network_required":False,"pure":True,"validation":"acceptance_pending",
    "entrypoint":{"callable":MODULE+":"+r["function"],"argument_parameter":"args","bound_arguments":{}}},
   "error_contract":{"direct_exception":"ScientificToolError","fields":["code","message","retryable"],
    "codes":["invalid_arguments","missing_dependency","incompatible_dependency","resource_limit","invalid_result","unsupported_conditions","upstream_failure"],
    "retry_policy":"Correct inputs or prepare pinned private environment before retrying deterministic failures."},
   "tags":["geology","geophysics","rock-physics",r["package"]],"registration_metadata":meta(s)}
  tools.append(spec)
  examples[r["tool_id"]]=r["example"]
  candidates.append({"tool_id":r["tool_id"],"capability_key":"geophysics:"+r["function"].replace("_","-"),
   "upstream_callable":r["upstream_callable"],"scientific_task":r["scientific_task"],
   "distinct_from_existing":r["distinct_from_existing"],"numeric_oracle":r["numeric_oracle"],"status":STATUS})
  dump(ROOT/fixture,{"synthetic":True,"status":STATUS,"tool_id":r["tool_id"],"input_source":SYNTHETIC,
   "arguments":r["example"],"expected_checks":r["expected"],"negative_overrides":r["negative"],
   "numeric_oracle":r["numeric_oracle"],"upstream_source":url,"limitations":limits})
 active_by_id={tool["id"]:tool for tool in tools}
 def selected(start,stop=None):
  return [active_by_id[r["tool_id"]] for r in ROWS[start:stop] if r["tool_id"] in active_by_id]
 workflows=[
  ("github-geophysics-potential-fields","Gravity and magnetic source modeling",selected(0,4),
   "Use for gravity or magnetic forward responses from explicit sources in local Cartesian coordinates.",
   "Choose point or finite-prism geometry from physical source scale. Confirm ENU axes and signed contrasts. Reject singular/interior observations. Inspect full vector/tensor fields together."),
  ("github-geophysics-effective-media","Effective rock moduli and mixture bounds",selected(4,11),
   "Use for mineral mixtures, pores and randomly oriented cracks with known phase properties.",
   "Begin with VRH or Hashin-Shtrikman bounds. Select the pore/inclusion theory justified by the physical question. Different constitutive models are alternative assumptions, not repeated measurements."),
  ("github-geophysics-grain-fracture","Grain contacts, cement and fracture mechanics",selected(11,17),
   "Use for dry-frame predictions controlled by contacts, cement, loading, cracks or sand-shale texture.",
   "Select the observed mechanism: aligned cracks, unbonded grains, deposited cement, prebonded contacts or shale packing. Johnson stress anisotropy is blocked and unavailable. Supply measured/calibrated parameters."),
  ("github-geophysics-fluid-effects","Pore-fluid substitution and seismic dispersion",selected(17,24),
   "Use for supplied pore fluids and rock frames, including static saturation and dynamic flow.",
   "Apply PVT/Brie only within the empirical assumptions. Choose Gassmann for isotropic equilibrium, Brown-Korringa for anisotropic compliance, or Biot/squirt/patch models for their distinct relaxation scales."),
  ("github-geophysics-seismic-interpretation","Layered and anisotropic seismic interpretation",selected(24),
   "Use for fine layering, anisotropic propagation, azimuthal AVO, elastic scattering or impedance.",
   "Backus requires subwavelength layers. Verify tensor symmetry before VTI/HTI use. Choose exact isotropic Zoeppritz or weak-HTI Ruger for the stated medium. Elastic impedance requires an explicit reference ratio.")]
 skills=[]
 for key,title,group,when,workflow in workflows:
  ids=[t["id"] for t in group]
  path="catalog/skills/"+key+"/SKILL.md"
  sm=copy.deepcopy(group[0]["registration_metadata"])
  sm.update(provider="GeoAgent",source_commit=None,license=None,pending_fields=["adapter_license","receiving_lab_approval","private_cpu_acceptance"])
  skills.append({"id":key,"name":title,"description":when+" "+workflow,"tool_references":ids,"skill_file":path,
   "metadata":{"canonical_skill_file":path,"validation":"not_run"},
   "delivery":{"source_candidates":ids,"unavailable_references":["GeoRockStressAnisotropy"] if key=="github-geophysics-grain-fracture" else [],"availability_status":"tool_candidates_available_workflow_unverified",
    "workflow_validation":"not_run","deployment_status":"not_deployed","submission_status":"not_submitted","model_workflow_validation":"not_run","receiving_lab_approval":"pending"},"registration_metadata":sm})
  front="---\nid: "+key.replace("-","_")+"\nname: "+json.dumps(title)+"\ndescription: "+json.dumps(when+" "+workflow)+"\nwhen_to_use: "+json.dumps(when)
  front+="\ntools:\n"+"".join("- "+id+"\n" for id in ids)
  front+="required_inputs:\n- Supplied finite model properties with explicit units and input_source provenance\nconstraints:\n- Select the physical model justified by inputs and its limitations.\n- Never infer mineral presence, grade or reserves.\n- No online retrieval or automatic installation.\nexpected_outputs:\n- Numeric JSON with units, pinned source release and input/implementation hashes\n---\n"
  body="\n# "+title+"\n\n## When to use\n\n"+when+"\n\n## Required inputs\n\nUse each strict JSON schema. Every example is SYNTHETIC and is not a field observation.\n\n## Workflow\n\n"+workflow+"\n\n## Tools and examples\n"
  fence=chr(96)*3
  for t in group:
   body+="\n### "+t["id"]+"\n\n"+t["description"]+"\n\nSynthetic fixture: "+t["example_path"]+"\n\n"+fence+"json\n"+json.dumps(t["example_arguments"],indent=2)+"\n"+fence+"\n"
   body+="\nLimitations: "+" ".join(t["limitations"][:-3])+"\n\nUpstream: "+t["metadata"]["upstream"]["source_url"]+"\n"
  body+="\n## Source interface\n\nNamed entrypoints in "+MODULE+" accept args=dict or JSON-object-string through @operation. Pure numeric calls need no output_dir and return artifacts=[]. Errors use ScientificToolError. Preserve units and provenance.\n"
  body+="\n## Expected outputs and interpretation\n\nA forward response does not establish that the modeled geological body exists. No measured validation or uncertainty calibration is supplied.\n"
  body+="\n## Dependencies and licensing\n\nPins: "+", ".join(PINS)+". Missing packages belong in a private CPU worker. Bruges: Apache-2.0; Choclo: BSD-3-Clause; rockphypy: GPLv3; rock-physics-open: LGPLv3. R2 retains shared pins, including typing-extensions4.16.0; never downgrade pydantic/langgraph. Adapter licensing and redistribution review remain pending.\n"
  body+="\n## Validation and availability\n\nR2 NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. source_authored_unverified. R1 basic30 passed according to parent, but counterexamples block promotion and that result is not r2 acceptance. Historical reports remain unchanged. GeoRockStressAnisotropy is blocked, not registered or counted. Unit, workflow, model and platform acceptance not_run; receiving lab pending. Existing online229 unchanged. Test source: tests_local/test_github_expansion_geophysics.py. Parent owns additive registry merge, fixed dispatch and CPU acceptance.\n"
  (ROOT/path).parent.mkdir(parents=True,exist_ok=True)
  (ROOT/path).write_text(front+body,encoding="utf-8")
 dump(GROUP/"catalog-additions.json",{"tools":tools,"skills":skills})
 dump(GROUP/"examples-additions.json",examples)
 dump(GROUP/"candidate-operations.json",{"group":"geophysics","operations":candidates})
 sources=[]
 for package,s in SOURCES.items():
  sources.append({"package":package,**s,"repository_url":"https://github.com/"+s["repository"],
   "release_metadata_url":"https://pypi.org/pypi/"+package+"/"+s["version"]+"/json",
   "release_tag_url":"https://github.com/"+s["repository"]+"/tree/"+s["tag"],
   "license_url":"https://github.com/"+s["repository"]+"/blob/"+s["commit"]+"/"+s["license_file"],
   "local_license_evidence":DELIVERY+"/licenses/"+package+".txt",
   "reviewed_source_files":sorted({r["source_file"] for r in ROWS if r["package"]==package} | ({"src/rock_physics_open/shale_models/pq.py"} if package=="rock-physics-open" else set())),
   "release_tag_commit_evidence":"Read-only GitHub tags API. Parent reports r2 rock-physics-open/tmatrix SHA and wheel ABI checked; scientific acceptance NOT RUN by this agent.","status":STATUS})
 dump(GROUP/"sources.json",{"group":"geophysics","sources":sources,"status":STATUS,
  "additional_dependency_evidence":{"tmatrix==1.2.0":{"release_url":"https://pypi.org/project/tmatrix/1.2.0/","publishing_commit":"51692ac838722fe78513bb5da60b72309e77ea57","role":"Declared private-worker dependency; no T-matrix operation added"},"typing-extensions==4.16.0":"Parent-confirmed existing private CPU pin, retained without downgrade","KDE-diffusion==1.0.5":"https://pypi.org/pypi/KDE-diffusion/1.0.5/json","shared_pins":"User-provided deployed CPU metadata preserved without install/downgrade."},
  "excluded_candidates":[{"callable":"rockphypy.EM.EM.Berryman_DEM","reason":"Release DEM passes G_eff,K_eff to PQ(Km,Gm,...) and uses -G_eff for shear contrast. Excluded; no kernel replacement.","source_url":"https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py"}],
  "blockers":["R2 changes NOT TESTED. Parent owns private CPU acceptance; r1 basic30 passing report is historical only.",
    "GeoRockStressAnisotropy is BLOCKED and absent from additions: incorrect Johnson logarithm, no accepted maintained replacement.",
    "SelfConsistent uses rock-physics-open1.0.1 and tmatrix1.2.0, installed and dependency-checked by parent; scientific acceptance remains pending.",
   "Parent reports private dependency compatibility; this r2 numeric/schema source has NOT RUN.",
   "GPLv3 dependency must remain explicit; adapter license and receiving-lab review pending.",
   "Parent must merge additive metadata and fixed module dispatch."]})
 emit_r2_evidence()
 (GROUP/"requirements-geophysics.txt").write_text("# Private CPU candidate profile. Parent reports dependencies installed; R2 SCIENCE NOT TESTED. Preserve shared env.\n"+"\n".join(PINS)+"\n",encoding="utf-8")
 (ROOT/ASSET/"README.md").write_text("# Synthetic geophysics fixtures\n\nAll fixtures are SYNTHETIC analytic evidence, never observations. Expected values use independent mathematical limits, surface integrals or hand-evaluated constitutive equations, not upstream snapshots. R2 tests have NOT RUN. R1 basic30 pass was reported by parent but does not validate r2 or remove recorded counterexamples. GeoRockStressAnisotropy.json is retained historical evidence only, not a candidate. Numeric validation does not establish field accuracy.\n",encoding="utf-8")
 print(json.dumps({"group":"geophysics","source_tools":len(tools),"blocked_tools":sorted(BLOCKED_IDS),"workflow_skills":len(skills),"status":STATUS,"tests_run":False,"deployed":False,"submitted":False}))

if __name__=="__main__":
 build()
