"""Native registrations of existing source algorithms, using their source schemas.

No argument translation, prose parsing, secondary dispatch or algorithm copies.
ToolOutput is only the runtime's common execution-result envelope.
"""
from ...tools import Tool, ToolDefinition, ToolOutput


def register(registry):
    from legacy.ToolsAgent.ToolsFuns.Geoscience import geoscience_common as source
    from legacy.ToolsAgent.ToolsFuns.source_contracts import definition

    functions = (
        ("GeoHaversineDistance", source.geo_haversine_distance,
         "Great-circle distance between supplied geographic coordinates; spherical approximation, not an ellipsoidal survey distance."),
        ("GeoBearing", source.geo_bearing,
         "Initial great-circle bearing clockwise from north between distinct, non-antipodal coordinates."),
        ("GeoDecimalToDMS", source.geo_decimal_to_dms,
         "Convert one latitude or longitude in decimal degrees to degrees, minutes and seconds."),
        ("GeoWGS84BBoxAreaKm2", source.geo_wgs84_bbox_area_km2,
         "Spherical area of an ordered longitude-latitude bounding box not crossing the antimeridian; not ellipsoidal area."),
        ("GeoCheckCRSConsistency", source.geo_check_crs_consistency,
         "Compare supplied CRS identifier strings. This does not prove dataset CRS correctness, resolve aliases, or reproject coordinates."),
    )
    for name, function, usage in functions:
        contract = definition(name)
        def execute(args, context, function=function):
            context.check()
            return ToolOutput(function(args))
        registry.register(Tool(ToolDefinition(name, contract["description"], usage,
                               contract["input_schema"], contract["output_schema"]), execute, pure=True))
