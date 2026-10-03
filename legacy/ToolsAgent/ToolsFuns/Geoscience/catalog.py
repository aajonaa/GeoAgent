"""Text contracts implemented by geoscience_common; shared with the planner."""

_COORDINATES = "Native text: lat1,lon1;lat2,lon2 in decimal degrees; do not wrap in JSON."

TOOL_SPECS = [
    {"Name": "GeoCheckCRSConsistency", "Function": "Compare explicit coordinate reference system identifiers.",
     "Input": "Native text: CRS identifiers separated by commas or semicolons, e.g. EPSG:4326,EPSG:3857.",
     "Output": "Text describing the normalized identifiers and whether they are consistent."},
    {"Name": "GeoHaversineDistance", "Function": "Compute great-circle distance on the WGS84 mean-radius sphere.",
     "Input": _COORDINATES, "Output": "Text containing great-circle distance in kilometres."},
    {"Name": "GeoMagnitudeToEnergy", "Function": "Estimate radiated earthquake energy using log10(E[J]) = 1.5 Mw + 4.8.",
     "Input": "Native text: a single numeric moment magnitude Mw, e.g. 6.5; do not wrap in JSON.",
     "Output": "Text containing magnitude, energy in joules and approximate tons TNT equivalent."},
    {"Name": "GeoBearing", "Function": "Compute the initial bearing between two explicit coordinates.",
     "Input": _COORDINATES, "Output": "Text containing the initial bearing in degrees clockwise from north."},
    {"Name": "GeoDecimalToDMS", "Function": "Convert a decimal-degree coordinate to degrees, minutes and seconds.",
     "Input": "Native text: <value>[,lat|lon], e.g. -35.5,lat; do not wrap in JSON.",
     "Output": "Text containing degrees, minutes, seconds and hemisphere or sign."},
    {"Name": "GeoWGS84BBoxAreaKm2", "Function": "Estimate the area of a longitude/latitude bounding box on a sphere.",
     "Input": "Native text: min_lon,min_lat,max_lon,max_lat in decimal degrees; do not wrap in JSON.",
     "Output": "Text containing the estimated bounding-box area in square kilometres."},
]

for _spec in TOOL_SPECS:
    _spec.update(Category="Geoscience", Source="ToolsFuns.Geoscience.geoscience_common")

TOOL_SPEC_BY_NAME = {spec["Name"]: spec for spec in TOOL_SPECS}


def get_tool_spec(name: str) -> dict | None:
    return TOOL_SPEC_BY_NAME.get(name)
