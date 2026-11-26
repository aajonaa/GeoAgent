# R2 independent synthetic oracles

Status: SOURCE AUTHORED, NOT TESTED. These are fixture-construction formulas,
not runtime scientific replacements and not output snapshots from upstream.

## Sources and independence

Primary tensor reference: W. J. Parnell, Journal of Elasticity 125 (2016),
DOI https://doi.org/10.1007/s10659-016-9573-6 .
Author preprint https://arxiv.org/html/1507.07165 , sections 3.2 and 3.3,
Appendix A.2 and rotational tensor projections.

The generator uses a Kelvin-tensor Hill-polarization route, not the scalar
F1...F9 formulas in Equinor pq.py or rockphypy PQ. It imports only stdlib,
does not call an upstream package, and does not solve the nonlinear SCA model.
The construction below is derived from the reference's Green-tensor integral.

## Closed angular moments

Let a spheroid have semiaxes (1,1,a), a uniform unit vector n, and
q=(n_x,n_y,n_z/a)/norm(n_x,n_y,n_z/a). Set t=n_z.

J2 = integral_0^1 t^2/[a^2+(1-a^2)t^2] dt.
J4 = integral_0^1 t^4/[a^2+(1-a^2)t^2]^2 dt.

For a=1: J2=1/3, J4=1/5 exactly, with no perturbation of a.
For a>1, b=a^2-1 and L=ln(a+sqrt(b)):
J2=a*L/b^(3/2)-1/b;
J4=(a^2+2)/(2*b^2)-3*a*L/(2*b^(5/2)).
For a<1, b=1-a^2 and L=acos(a):
J2=1/b-a*L/b^(3/2);
J4=(a^2+2)/(2*b^2)-3*a*L/(2*b^(5/2)).
Only moderate aspects 0.5,1,2,3 are used in this analytic evidence.

Mzz=J2; Mxx=Myy=(1-J2)/2.
Mzzzz=J4; Mxxzz=Myyzz=(J2-J4)/2.
Mxxxx=Myyyy=3*(1-2*J2+J4)/8; Mxxyy=(1-2*J2+J4)/8.
Odd moments vanish; fourth moments are symmetric under index permutation.

For host lambda=K-2G/3 and beta=(lambda+G)/(lambda+2G), the Hill tensor is

H_ijkl = [delta_ik*Mjl + delta_il*Mjk + delta_jk*Mil +
          delta_jl*Mik - 4*beta*Mijkl]/(4G).

Represent symmetric tensors in an orthonormal Kelvin basis, with off-diagonal
basis entries 1/sqrt(2), not engineering-Voigt shear weights.
A=[I+H:(Ci-C)]^-1. Its rotational projections are
P=sum(A_ab for a,b in {xx,yy,zz})/3 and Q=(trace(A)-P)/5.
This six-dimensional matrix construction is independent of upstream scalar
geometric-factor implementations. GPa are consistent throughout fixture
construction; runtime conversion to Pa is separately required and tested.

## Exact heterogeneous spheres

Two equally weighted phases: (K,G)=(4,3),(16,12) GPa, a=1 for both.
Along K=4G/3, spherical bulk and shear concentration factors coincide.
The equal-fraction equations reduce to G^2=3*12=36.
Expected K=8 GPa, G=6 GPa, density=(2400+2800)/2=2600 kg/m3.
Both phase moduli contrast, so this is not a homogeneous identity test.

## Nonzero heterogeneous prolate and mixed-shape cases

Prescribe K*=8,G*=6 GPa and three phases:
K=[4,16,8], G=[3,3,12] GPa, rho=[2400,2700,3000] kg/m3.
Use aspects [2,3,2] and separately [0.5,1,2].
Evaluate independent Hill/Kelvin P_i,Q_i at the prescribed target.
Let D_i=(K_i-K*)P_i and E_i=(G_i-G*)Q_i.
D_3=0, D_1<0,D_2>0; E_1,E_2<0,E_3>0.
Choose unnormalized weights w1=1,w2=-D1/D2,
w3=-(E1+w2*E2)/E3, then f_i=w_i/sum(w).

All three phases have positive volume. Both self-consistent balances vanish
by linear algebra at the prescribed target. No upstream output or nonlinear
solver is used to obtain expected K,G. Expected density=sum(f_i*rho_i).
The generated fixture contains the independent concentration factors for audit.

## Residual rejection, not kernel repair

Equinor multi_sca stops on bulk change alone. Equal bulk phases K=[10,10]
and contrasting G=[3,12] reach a zero bulk update before the shear equation
converges. The negative case requires invalid_result from the dual-residual
gate. This limitation remains disclosed; no local corrected solver is provided.

## Other r2 domain counterexamples

HTI negatives use isotropic Snell critical angle 30 degrees, the exact critical
boundary, and a weak HTI tensor whose horizontal qP speed makes 30 degrees
postcritical despite its smaller vertical speed. The runtime quadratic
Christoffel gate tests propagation, not reflection amplitude replacement.

Squirt-flow negatives independently show: smaller dry velocities do not imply
smaller dry bulk modulus; positive wet shear can exceed the crack-free bound;
and crack compliance can produce negative wet shear compliance. The positive
case has genuinely nonzero bulk/shear crack compliance and Gwet=50/7 GPa.

## Blocked stress diagnostic

The historical equal-strain fixture is retained, not counted or overwritten.
For unequal strains alpha=0.5, use the independent antiderivative
I0=[sqrt(1+alpha^2)+alpha^2*asinh(1/alpha)]/2 and integration-by-parts
I2=[(1+alpha^2)^(3/2)-alpha^2*I0]/4,
I4=[(1+alpha^2)^(3/2)-3*alpha^2*I2]/6.
The original upstream logarithm differs. An expected-failure diagnostic
retains this evidence without enabling the blocked operation.

R1 basic30 passing was reported by parent and is historical only.
No scientific tests were executed while authoring r2.
