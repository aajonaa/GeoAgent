# Native tool inventory merge

## Counting convention

The supplied GeoToolAgent inventory contains 110 named entries, already represented in this project. This is an implementation/contract merge, not 110 extra tools. Preserve those IDs and six additional scientific imaging/interpolation tools: 116 professional entries. Archive 62 placeholders outside the live catalog. Runtime tools are counted separately and depend on enabled services. Names in different scientific categories can share an algorithm; this inventory is not a count of distinct algorithms.

## Contracts

Source functions consume named objects and return typed objects. The canonical catalog owns input/output schemas, descriptions, units, constraints, path roles, native entry points and examples. No legacy planner/capability layer or action-JSON adapter is imported. Existing working algorithms are preserved. Incoming IDW method is retained with explicit value field, WGS84 distance and pixel-center grid contracts. Metadata, Skill instructions and function definitions must agree.

27 previously blocked data/backend operations now operate on explicit caller-supplied snapshots. Callers supply the file and dataset version; results include SHA-256 and byte size. This does not supply, certify, license or recreate a missing global database. LITHO and SEMUCB operations query supplied node/sample tables. Event/model joins are precomputed lookups, not fresh tomography sampling. QC summarizes existing flags. Ocean averages are observation-weighted, not area-weighted. See each schema and limitation.

GeoSPARQL executes local RDF SELECT through RDFLib, with CRS84 Simple Features predicates. It does not compare a query to benchmark answers. Remote SERVICE, FROM and update clauses are rejected. This is a documented subset, not full OGC conformance.

Landsat CloudMask uses Landsat 8/9 Collection 2 QA_PIXEL bits 0-5; it is not a Sentinel-2 QA decoder or QA_RADSAT processor. NDTI requires aligned same-acquisition red/green reflectance and is not a calibrated sediment concentration. No automatic resampling or silent unit conversion.

USGS fetch uses the official endpoint, typed dates and bounds, an explicit returned limit flag, structured errors and no pure-result cache. Its service availability and scientific coverage are separate from offline contract acceptance. Earthquake maps are safe static coordinate plots, not remote-tile interactive basemaps.

## Validation and delivery status

Synthetic fixtures are exclusively acceptance inputs. They are never knowledge-base observations or real scientific evidence. Run tests_local/test_native_merge.py for independent object/JSON/transport calls and numerical/pixel oracles; test_professional_catalog.py exercises every registered professional tool via the runtime. Test_library.py checks UI contracts and retains blocked-asset behavior using explicit negative fixtures. Result reports record actual acceptance separately from source registration status.

This change is not a lab-certified handoff package. Provider, redistribution permissions, official protocol version and platform acceptance remain pending where unknown. Skill tool availability does not establish end-to-end workflow validation. Do not mark workflow_validation or platform_validation passed without that validation.

## Source attribution

Incoming project: GeoToolAgent, MIT, Copyright (c) 2024 Jing Yu. Retain original license/notice when redistributing derived material; dataset licenses are independent. Existing current implementations take precedence over older incoming routines. No third-party dataset is bundled here.

## Method references

- [USGS Event API](https://earthquake.usgs.gov/fdsnws/event/1/)
- [USGS Landsat Collection 2 QA bands](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)
