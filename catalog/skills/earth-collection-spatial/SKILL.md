---
id: "earth_collection_spatial"
name: "Earth collection spatial"
description: "Bounded upstream spatial operations with explicit schemas, physical units, evidence and artifact outputs."
when_to_use: "Bounded upstream spatial operations with explicit schemas, physical units, evidence and artifact outputs."
tools: ["GeoPyshedsFlowAccumulation", "GeoPywrWaterAllocation", "GeoHoloViewsLineProfile", "GeoGeoViewsPolygonMap", "GeoHVPlotHexbin", "GeoPanelDataReport", "GeoGeemapBoundingPolygon", "GeoCollocatePressureMatch", "GeoSalemProjectCoordinates"]
required_inputs: ["Arguments and datasets declared by the selected tool's input schema"]
constraints: ["Choose only operations relevant to the current task; do not load the entire collection.", "Use supplied data and declared units; never fabricate measurements or execution evidence.", "Never install dependencies, download data, execute arbitrary scripts or load untrusted serialized models during a tool call.", "Report missing prerequisites honestly. Missing runtime dependencies are not missing user research intent.", "Use only returned artifact paths and preserve source provenance and scientific limitations."]
expected_outputs: ["Observed schema-valid results with explicit units and provenance", "Real registered previews/data files only where the tool declares outputs"]
---

# Earth collection spatial

Bounded upstream spatial operations with explicit schemas, physical units, evidence and artifact outputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Artifact-producing standalone calls require output_dir set to a new or empty directory. Native execution snapshots task-relative inputs and registers generated result files.

- GeoPyshedsFlowAccumulation: `geological_agent.geology.collection_spatial:pysheds_flow_accumulation`. Compute D8 flow direction and contributing-cell counts from a finite, square-cell projected DEM using pysheds.
- GeoPywrWaterAllocation: `geological_agent.geology.collection_spatial:pywr_water_allocation`. Solve one-day water supply allocation to prioritized demands using the real Pywr linear programming model.
- GeoHoloViewsLineProfile: `geological_agent.geology.collection_spatial:holoviews_line_profile`. Render a supplied ordered geological or environmental profile to PNG and SVG using HoloViews and Matplotlib.
- GeoGeoViewsPolygonMap: `geological_agent.geology.collection_spatial:geoviews_polygon_map`. Render supplied WGS84 polygon values to an offline choropleth PNG/SVG with GeoViews, without a downloaded basemap.
- GeoHVPlotHexbin: `geological_agent.geology.collection_spatial:hvplot_hexbin`. Render paired observations as a count-colored hexbin plot using the upstream hvPlot hexbin operation.
- GeoPanelDataReport: `geological_agent.geology.collection_spatial:panel_data_report`. Create a standalone offline HTML report from an escaped CSV table using Panel, with no model-generated executable HTML or server.
- GeoGeemapBoundingPolygon: `geological_agent.geology.collection_spatial:geemap_bounding_polygon`. Convert an ordered WGS84 bounding box into a polygon Feature using the actual geemap utility, without Earth Engine.
- GeoCollocatePressureMatch: `geological_agent.geology.collection_spatial:collocate_pressure_match`. Select a measured value using collocate's original nearest-pressure-ratio kernel; retain source order for ties.
- GeoSalemProjectCoordinates: `geological_agent.geology.collection_spatial:salem_project_coordinates`. Transform bounded coordinate arrays using Salem's original projection functions without auto-downloading its graphics data.

### Current availability

tool_candidates_available_workflow_unverified

All listed entries have concrete source operations; this is not execution proof. Workflow validation: not_run. Platform validation: not_run. Original archive revisions and separately pinned published releases are not assumed byte-identical. Formal receiving AI Lab approval remains pending.
