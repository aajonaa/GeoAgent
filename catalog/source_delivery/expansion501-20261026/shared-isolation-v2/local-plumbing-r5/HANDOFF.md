# Shared-only GPR plumbing r5

Proposed fixed profile ID: `expansion501-geology-gpr-cpu-v2`. No runtime profile is registered.
Parent owns `catalog/source_delivery/expansion501-20261026/groups/geology/catalog-additions.json`
and its generator; this change edits neither. Peirce's six-pin contract is preserved.

For GeoConditionedResourceEnsemble ONLY, parent may add the contents of
`gpr-isolation.schema.json` as output_schema.properties.provenance.properties.isolation.
Do NOT add isolation to provenance.required: the existing child decorator validates
before the main bridge appends verified isolation evidence. The optional object is
closed and all 14 internal fields are required. installed_versions has exactly the
six existing pins; native_projects is an empty closed object; protocol/profile_id
are constants and all three capability booleans are false.

Do not add registration_metadata.runtime.isolation_profile_id to the main catalog
until a real administrator profile is prepared and accepted. A private acceptance
catalog may bind the fixed ID. The empty shipped allowlist remains unchanged.

The fixed worker sets GEOAGENT_EXPANSION501_GEOLOGY_CPU=expansion501-geology-cpu-v1
only inside its validated, process-local child context, for the fixed profile ID,
tool, module and callable. It restores prior environment state afterward.
Neither user arguments nor an administrator-provided arbitrary environment map
controls the marker. Child dependency checks remain unchanged and mandatory.
The marker is not an OS sandbox and is not sufficient authentication on its own.

This source pass uses the existing Windows private Python/jsonschema only.
The original 41 tests are unchanged; 11 additional tests cover schema and the
internal marker policy with clearly synthetic contexts. These tests are NOT real
GPR calls or scientific acceptance. No GPR build/license receipt is fabricated,
no deployment profile is enabled, and there is no Linux retry or replacement of
the policy-denied remote installation. GPR scientific acceptance remains not_run.

Prior manifests/reports are retained. The live source-package-manifest records
the actual worker hash and latest local report. The frozen parent r7/r3 overlays
are not modified; parent must explicitly select this new overlay revision.
