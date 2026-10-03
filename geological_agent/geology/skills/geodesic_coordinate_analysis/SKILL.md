---
id: geodesic_coordinate_analysis
name: Geodesic and coordinate analysis
description: Distance, initial bearing, coordinate conversion, bounding-box area and CRS identifiers. 地理距离、方位角、经纬度转换、区域面积、坐标系标识。
when_to_use: Supplied coordinates or CRS identifiers require spatial calculations without external datasets.
required_inputs: [Coordinates in degrees or CRS identifier strings]
tools: [GeoHaversineDistance, GeoBearing, GeoDecimalToDMS, GeoWGS84BBoxAreaKm2, GeoCheckCRSConsistency]
constraints:
  - Distance and area use the sphere of radius 6371.0088 km, not an ellipsoidal geodesic.
  - Longitude is east-positive and latitude north-positive; use explicit named parameters.
  - Bearing is initial and clockwise from north; coincident or antipodal points are undefined.
  - Bounding boxes cannot cross the antimeridian; ask before choosing a different region.
  - CRS checks compare normalized text identifiers only; they do not validate data or transform coordinates.
expected_outputs: [Requested quantities with units and method limitations]
---
# Geodesic and coordinate analysis

Use the exposed native tool definitions with the user's coordinates. Select only
operations required by the question. Independent calculations may be sent as
multiple native tool calls in the same response. Their results remain separate
observations with individual call IDs.

GeoHaversineDistance returns distance_km. GeoBearing returns bearing_degrees.
Both take lat1, lon1, lat2 and lon2 in degrees. GeoDecimalToDMS takes value and
axis (lat or lon). GeoWGS84BBoxAreaKm2 takes min_lon, min_lat, max_lon, max_lat.
GeoCheckCRSConsistency takes crs_values and checks normalized identifier text.
Schemas are authoritative for valid types and bounds. Do not silently reorder
coordinates or reinterpret ambiguous units.

Use successful tool results directly in a concise answer. Round for presentation
only. No file creation or Python execution is necessary unless the user requests
files or a calculation beyond these tools. Do not repeat successful calls to
check formatting. Correct invalid inputs from actual feedback, or ask for the
missing information. Never fabricate a result from a failed call.
