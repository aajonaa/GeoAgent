# Bouguer SI boundary correction, r7

Source-stable, unverified. Existing operation: GeoGravityBouguerSlab.
The only scientific adapter edit wraps the existing upstream call as
(harmonica.bouguer_correction(...) * 1e-5). Native arguments and all
height, mass, density and sign conventions are unchanged. Harmonica
returns mGal; the existing declared result is SI m/s^2.

Independent references use 2*pi*G*rho*h on land and
2*pi*G*(rho_water-rho_crust)*abs(h) underwater, with G=6.67430e-11 SI.
The marine deficit stays negative; zero elevation and equal underwater
densities stay zero. Existing SI assertions and tolerances were not edited.

Five boundary-only tests and four real-pinned-upstream boundary tests
were authored. NONE were run in this revision. Boundary test doubles
are not scientific acceptance. Real upstream tests explicitly skip
when exact declared dependencies are absent; imports are not attempted
until the pin gate is satisfied. These focused tests do not certify
the full decorated runtime or the parent v2 dispatch path.

Before-source, before-manifest, original call, hashes and exact declared
requirements are retained in before/ and source-edit.json. Historical
r1 failures and the superseded v1 invalid-JSON failure remain untouched.
No Tesseroid/Edge/Eigenfunction change, install, remote operation,
GPU/model use, deployment, Git operation or push was performed.
