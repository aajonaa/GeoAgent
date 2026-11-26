from .geoscience_common import *


GEOSCIENCE_TOOLS_DICT = {
    "GeoCheckCRSConsistency": geo_check_crs_consistency,
    "GeoHaversineDistance": geo_haversine_distance,
    "GeoMagnitudeToEnergy": geo_magnitude_to_energy,
    "GeoBearing": geo_bearing,
    "GeoDecimalToDMS": geo_decimal_to_dms,
    "GeoWGS84BBoxAreaKm2": geo_wgs84_bbox_area_km2,
}
